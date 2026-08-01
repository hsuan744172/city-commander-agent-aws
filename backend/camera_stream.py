"""
路段即時影像 MJPEG 代理。

上游（twipcam 鏡像與各級政府 CCTV）多數只提供定時更新的 JPEG 快照，沒有 MJPEG
或 HLS 端點。本模組把「輪詢快照」轉成標準 multipart/x-mixed-replace 串流，前端
用一個 <img src="/api/cameras/.../stream"> 就能持續顯示，不必反覆換 src。

為什麼放後端而不是讓前端輪詢：
  1. 同一支鏡頭不論幾個前端在看，只向上游抓一次，不會 N 倍放大外部流量。
  2. 前端不直連第三方網域，避開防盜連與 HTTP 頁面載入外部資源的風險。
  3. 只有 data/segment_cameras.json 列出的鏡頭可被代理，外部無法用參數指定任意
     網址，避免變成 SSRF 跳板。
  4. 上游的 Last-Modified 只有後端讀得到（<img> 讀不到），因此能判斷畫面新舊。

畫面來源有兩種，由 CAMERA_MOCK 決定（見 _mock_mode）：
  upstream — 真實公開 CCTV 快照
  mock     — 後端合成的模擬街景（backend/mock_camera.py）

實測公開來源的台北市快照已數小時未更新，Demo 會整片靜止，因此預設 auto 模式在
上游取不到或畫面過舊時自動切換為合成畫面，並以「當下模擬時間」作為畫面時間，
在儀表板上呈現為即時影像。

本模組純屬畫面呈現，不參與 SOP 判定與 ETE 計算。
"""

from __future__ import annotations

import asyncio
import contextlib
import email.utils
import hashlib
import logging
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from backend import mock_camera, sim_clock

logger = logging.getLogger(__name__)

# 向上游取新畫面的間隔。實測台北市快照更新遠慢於此，再快只是浪費對方頻寬。
POLL_SECONDS = 5.0
# 畫面沒變也重送一幀，避免中間的反向代理判定連線閒置而中斷。
KEEPALIVE_SECONDS = 20.0
# 最後一個訂閱者離開後，輪詢再撐這麼久才收工（換鏡位、重新整理不必重啟輪詢）。
IDLE_SHUTDOWN_SECONDS = 30.0
UPSTREAM_TIMEOUT = 15.0
# 單幀上限，防止上游回傳異常大的內容把記憶體吃光。
MAX_FRAME_BYTES = 4 * 1024 * 1024
# 上游畫面超過這個秒數就認定過舊。auto 模式據此決定是否改用合成畫面。
STALE_AFTER_SECONDS = 180.0
# 上游／合成的判定結果快取多久後重新評估（上游修好了也能自動回去用真畫面）。
MODE_RECHECK_SECONDS = 300.0

BOUNDARY = "citycommanderframe"
MJPEG_CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"

_USER_AGENT = "city-commander-agent/2.1 (traffic operations dashboard)"
# 對外輸出時間格式，與全專案一致
TIME_FMT = "%Y-%m-%d %H:%M"

# 模擬畫面模式 (CAMERA_MOCK)：
#   auto (預設) — 上游取不到或畫面過舊時改用後端合成畫面，Demo 不會開天窗
#   on          — 一律使用合成畫面，完全不連外
#   off         — 只用真實上游，取不到就顯示無訊號
MOCK_MODES = ("auto", "on", "off")

SOURCE_UPSTREAM = "upstream"
SOURCE_MOCK = "mock"


def _mock_mode() -> str:
    mode = (os.environ.get("CAMERA_MOCK") or "auto").strip().lower()
    return mode if mode in MOCK_MODES else "auto"


class UpstreamError(RuntimeError):
    """上游取像失敗，呼叫端應回 502 而不是吐出壞掉的串流。"""


@dataclass(frozen=True)
class CameraRef:
    """要代理的鏡頭。網址一律由對照表白名單提供，不接受呼叫端指定。"""

    segment_id: str
    camera_id: str
    url: str
    name: str = ""

    @property
    def key(self) -> str:
        return f"{self.segment_id}/{self.camera_id}"


@dataclass(frozen=True)
class Frame:
    data: bytes
    content_type: str
    fetched_at: datetime
    # 畫面所屬時間；上游快照取自 Last-Modified，合成畫面即為產生時間
    last_modified: datetime | None
    digest: str
    source: str = SOURCE_UPSTREAM

    @property
    def age_seconds(self) -> float | None:
        """畫面距今幾秒。上游沒給 Last-Modified 時無法判斷，回 None。"""
        if self.last_modified is None:
            return None
        return (datetime.now(timezone.utc) - self.last_modified).total_seconds()


# ---------------------------------------------------------------------------
# 取像：真實上游與合成畫面
# ---------------------------------------------------------------------------


def _fetch_upstream(url: str) -> Frame:
    """同步取一張上游快照。由 asyncio.to_thread 呼叫，不阻塞事件迴圈。"""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        # 網址僅來自 data/segment_cameras.json 的白名單，不接受外部輸入
        with urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT) as response:  # noqa: S310
            content_type = (response.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                raise UpstreamError(f"上游回傳非影像內容：{content_type}")

            data = response.read(MAX_FRAME_BYTES + 1)
            if len(data) > MAX_FRAME_BYTES:
                raise UpstreamError("上游影像超過單幀上限")
            if not data:
                raise UpstreamError("上游回傳空內容")

            raw_modified = response.headers.get("Last-Modified")
    except UpstreamError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpstreamError(f"{type(exc).__name__}: {exc}") from exc

    last_modified = None
    if raw_modified:
        with contextlib.suppress(TypeError, ValueError):
            parsed = email.utils.parsedate_to_datetime(raw_modified)
            if parsed is not None:
                last_modified = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    return Frame(
        data=data,
        content_type=content_type,
        fetched_at=datetime.now(timezone.utc),
        last_modified=last_modified,
        digest=hashlib.sha1(data, usedforsecurity=False).hexdigest()[:12],
        source=SOURCE_UPSTREAM,
    )


def _render_mock(ref: CameraRef) -> Frame:
    """合成一幀模擬街景。畫面時間即產生時間，因此永遠是新的。"""
    try:
        data = mock_camera.render(ref.segment_id, ref.camera_id, ref.name)
    except Exception as exc:  # 合成失敗不該讓整條串流掛掉
        raise UpstreamError(f"模擬畫面產生失敗 {type(exc).__name__}: {exc}") from exc

    now = datetime.now(timezone.utc)
    return Frame(
        data=data,
        content_type="image/png",
        fetched_at=now,
        last_modified=now,
        digest=hashlib.sha1(data, usedforsecurity=False).hexdigest()[:12],
        source=SOURCE_MOCK,
    )


# ---------------------------------------------------------------------------
# 來源判定
# ---------------------------------------------------------------------------

_decisions: dict[str, tuple[float, str]] = {}


async def _resolve_source(ref: CameraRef) -> str:
    """
    決定這支鏡頭要用真實上游還是合成畫面。

    auto 模式下先試上游：取不到、或畫面已過舊（實測公開來源常見數小時未更新），
    就改用合成畫面，避免 Demo 出現整片靜止的畫面。判定結果快取一段時間，
    上游恢復後會自動回頭使用真畫面。
    """
    mode = _mock_mode()
    if mode == "on":
        return SOURCE_MOCK
    if mode == "off":
        return SOURCE_UPSTREAM

    loop = asyncio.get_running_loop()
    cached = _decisions.get(ref.key)
    if cached and loop.time() - cached[0] < MODE_RECHECK_SECONDS:
        return cached[1]

    decision = SOURCE_MOCK
    try:
        frame = await asyncio.to_thread(_fetch_upstream, ref.url)
        age = frame.age_seconds
        if age is not None and age <= STALE_AFTER_SECONDS:
            decision = SOURCE_UPSTREAM
        else:
            shown = "無時間資訊" if age is None else f"已 {round(age / 3600, 1)} 小時未更新"
            logger.info(f"街景改用模擬畫面（上游{shown}）：{ref.key}")
    except UpstreamError as exc:
        logger.info(f"街景改用模擬畫面（上游不可用：{exc}）：{ref.key}")

    _decisions[ref.key] = (loop.time(), decision)
    return decision


# ---------------------------------------------------------------------------
# 共用輪詢
# ---------------------------------------------------------------------------


def _encode_part(frame: Frame) -> bytes:
    """組一個 multipart/x-mixed-replace 片段。"""
    header = (
        f"--{BOUNDARY}\r\n"
        f"Content-Type: {frame.content_type}\r\n"
        f"Content-Length: {len(frame.data)}\r\n\r\n"
    ).encode()
    return header + frame.data + b"\r\n"


class _Source:
    """單一畫面來源：一份共用取像迴圈，餵給任意數量的訂閱者。"""

    def __init__(
        self,
        key: str,
        producer: Callable[[], Frame],
        *,
        interval: float,
        always_publish: bool,
        kind: str,
    ) -> None:
        self.key = key
        self.kind = kind
        self.interval = interval
        # 合成畫面每幀都不同，不必比對指紋
        self.always_publish = always_publish
        self._producer = producer
        self.latest: Frame | None = None
        self.error: str | None = None
        self.subscribers: set[asyncio.Queue[Frame]] = set()
        self._task: asyncio.Task | None = None
        self._fetch_lock = asyncio.Lock()

    # --- 取像 ---------------------------------------------------------------

    async def refresh(self, max_age: float | None = None) -> Frame:
        """
        取一張夠新的畫面。快取還在 max_age 內就直接用，避免多個訂閱者同時湧入時
        對上游連發請求。
        """
        window = self.interval if max_age is None else max_age

        def fresh_enough(frame: Frame | None) -> bool:
            if frame is None or window <= 0:
                return False
            return (datetime.now(timezone.utc) - frame.fetched_at).total_seconds() < window

        if fresh_enough(self.latest):
            return self.latest  # type: ignore[return-value]

        async with self._fetch_lock:
            # 等鎖的期間可能已經有人抓好了
            if fresh_enough(self.latest):
                return self.latest  # type: ignore[return-value]

            try:
                frame = await asyncio.to_thread(self._producer)
            except UpstreamError as exc:
                self.error = str(exc)
                raise

            self.error = None
            self.latest = frame
            return frame

    # --- 訂閱 ---------------------------------------------------------------

    async def subscribe(self) -> AsyncIterator[Frame]:
        """
        訂閱這支鏡頭的畫面。先立刻給一張目前畫面，之後由取像迴圈推送。
        """
        queue: asyncio.Queue[Frame] = asyncio.Queue(maxsize=1)
        self.subscribers.add(queue)
        self._ensure_poller()
        try:
            first = self.latest or await self.refresh()
            yield first
            while True:
                yield await queue.get()
        finally:
            self.subscribers.discard(queue)

    def _publish(self, frame: Frame) -> None:
        """推給所有訂閱者。慢的客戶端只會拿到最新一幀，不累積延遲。"""
        for queue in list(self.subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(frame)

    # --- 取像迴圈 -----------------------------------------------------------

    def _ensure_poller(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop(), name=f"cam-{self.kind}-{self.key}")

    async def _poll_loop(self) -> None:
        last_digest = self.latest.digest if self.latest else None
        last_push = 0.0
        idle_since: float | None = None
        loop = asyncio.get_running_loop()

        while True:
            try:
                await asyncio.sleep(self.interval)

                now = loop.time()
                if not self.subscribers:
                    idle_since = idle_since or now
                    if now - idle_since >= IDLE_SHUTDOWN_SECONDS:
                        logger.info(f"街景取像收工（無人觀看）：{self.key}")
                        return
                    continue
                idle_since = None

                try:
                    frame = await self.refresh(max_age=0)
                except UpstreamError as exc:
                    logger.warning(f"街景取像失敗 {self.key}: {exc}")
                    continue

                # 畫面沒變就不重送，只在超過 keepalive 才補一幀維持連線
                changed = self.always_publish or frame.digest != last_digest
                if changed or now - last_push >= KEEPALIVE_SECONDS:
                    self._publish(frame)
                    last_digest = frame.digest
                    last_push = now

            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 取像不該因為意外錯誤整支掛掉
                logger.warning(f"街景取像異常 {self.key}: {type(exc).__name__}: {exc}")

    async def aclose(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


_sources: dict[str, _Source] = {}


def _build_source(ref: CameraRef, kind: str) -> _Source:
    if kind == SOURCE_MOCK:
        return _Source(
            ref.key,
            lambda: _render_mock(ref),
            interval=1.0 / mock_camera.FPS,
            always_publish=True,
            kind=SOURCE_MOCK,
        )
    return _Source(
        ref.key,
        lambda: _fetch_upstream(ref.url),
        interval=POLL_SECONDS,
        always_publish=False,
        kind=SOURCE_UPSTREAM,
    )


async def _source(ref: CameraRef) -> _Source:
    kind = await _resolve_source(ref)
    source = _sources.get(ref.key)
    # 對照表更新或來源判定改變時重建
    if source is None or source.kind != kind:
        if source is not None:
            await source.aclose()
        source = _build_source(ref, kind)
        _sources[ref.key] = source
    return source


# ---------------------------------------------------------------------------
# 對外介面
# ---------------------------------------------------------------------------


async def stream(ref: CameraRef) -> AsyncIterator[bytes]:
    """
    產生 multipart/x-mixed-replace 串流內容。

    呼叫端應先 await prime()，確認取得到畫面後再建立 StreamingResponse，
    這樣來源掛掉時能回 502 而不是一條空串流。
    """
    source = await _source(ref)
    async for frame in source.subscribe():
        yield _encode_part(frame)


async def prime(ref: CameraRef) -> Frame:
    """先確認取得到畫面；失敗時拋 UpstreamError。"""
    source = await _source(ref)
    return await source.refresh()


async def frame_info(ref: CameraRef) -> dict:
    """
    回報畫面狀態供前端顯示。取像失敗時不拋錯，改以 available=False 表達，
    讓面板能顯示無訊號。
    """
    source = await _source(ref)
    try:
        frame = await source.refresh()
    except UpstreamError as exc:
        return {
            "available": False,
            "source": source.kind,
            "is_mock": source.kind == SOURCE_MOCK,
            "upstream_error": str(exc),
            "is_stale": True,
        }

    age = frame.age_seconds

    # 合成畫面的時間軸跟著模擬時鐘，與畫面上的疊字、儀表板顯示一致；
    # 若回報真實時間，面板會出現「畫面攝於今天」而影像上寫著情境日期的矛盾。
    if frame.source == SOURCE_MOCK:
        captured_at = sim_clock.now_str()
    elif frame.last_modified:
        captured_at = frame.last_modified.astimezone().strftime(TIME_FMT)
    else:
        captured_at = None

    return {
        "available": True,
        "source": frame.source,
        "is_mock": frame.source == SOURCE_MOCK,
        "content_type": frame.content_type,
        "bytes": len(frame.data),
        "captured_at": captured_at,
        "fetched_at": frame.fetched_at.astimezone().strftime(TIME_FMT),
        "age_seconds": round(age) if age is not None else None,
        # 上游沒給 Last-Modified 時無從判斷新舊，不擅自標成即時
        "is_stale": True if age is None else age > STALE_AFTER_SECONDS,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "upstream_error": None,
    }


async def shutdown() -> None:
    """關閉所有取像任務。由 FastAPI lifespan 呼叫。"""
    sources = list(_sources.values())
    _sources.clear()
    _decisions.clear()
    for source in sources:
        await source.aclose()
