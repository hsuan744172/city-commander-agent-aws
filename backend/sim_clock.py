"""
模擬時鐘 (Simulation Clock) — 讓後端依「時間」輪播 mock data。

設計目標：
  1. 後端自己推進時間，前端只需要拉「當下狀態」，不需要知道時間軸。
  2. 時間可被外部調整（環境變數、REST API、單次請求 query 參數）。

五種模式 (SIM_CLOCK_MODE)：
  - smooth (預設)：與 playback 同樣的節奏（每 SIM_CLOCK_INTERVAL 秒走完一個資料間隔），
                   但時間是連續的，會落在兩個資料點之間 → 搭配資料插值可得平滑變化。
  - playback    ：每 SIM_CLOCK_INTERVAL 秒「跳」到下一個資料時間點，時間永遠落在資料點上。
  - auto        ：連續時間，模擬時間 = 錨點 + 真實經過秒數 × SIM_CLOCK_SPEED。
  - fixed       ：凍結在某個時間點（暫停 / 手動指定）。
  - latest      ：永遠取資料集最後一個時間點（等同改動前的舊行為）。

smooth / playback 都用「資料間隔」當節奏單位，因此資料集裡 1 小時的間隔與
15 分鐘的間隔在畫面上耗時相同，不會前段拖很久、後段一閃而過。

時間解析優先序：
  單次請求 override (?ts=) > contextvar override > 全域時鐘 now()
"""

from __future__ import annotations

import bisect
import logging
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# 時鐘在 module 載入時就會讀環境變數，因此必須確保 .env 已載入
# （不依賴呼叫端的 import 順序；load_dotenv 不會覆蓋既有環境變數）
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover — 沒裝 python-dotenv 也要能跑
    pass

logger = logging.getLogger(__name__)

from backend.data_source import get_data_path

TIME_FMT = "%Y-%m-%d %H:%M"
MODES = ("smooth", "playback", "auto", "fixed", "latest")

# 時間連續的模式（值會落在資料點之間，需搭配資料插值才平滑）
CONTINUOUS_MODES = ("smooth", "auto")

DEFAULT_MODE = "smooth"
DEFAULT_INTERVAL = 10.0   # smooth/playback：每 N 真實秒走完一個資料間隔
DEFAULT_SPEED = 60.0      # auto：模擬時間相對真實時間的倍率
DEFAULT_POLL = 2.0        # 連續模式建議的前端輪詢秒數
DEFAULT_LOOP = True


# ---------------------------------------------------------------------------
# 時間軸 (從資料集推導，帶 mtime 快取)
# ---------------------------------------------------------------------------

_timeline_cache: dict = {}
_timeline_lock = threading.Lock()


def _data_paths() -> tuple[Path, Path]:
    return (
        get_data_path("city_traffic_flow.csv"),
        get_data_path("signaling_crowd_density.csv"),
    )


def _cache_key() -> tuple:
    return tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in _data_paths())


def timeline() -> list[pd.Timestamp]:
    """資料集中所有出現過的時間點（去重、升冪）。"""
    paths = _data_paths()
    key = tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in paths)
    with _timeline_lock:
        if _timeline_cache.get("key") == key:
            return _timeline_cache["timeline"]

        stamps: set[pd.Timestamp] = set()
        for path in paths:
            if not path.exists():
                continue
            try:
                col = pd.read_csv(path, usecols=["Timestamp"], parse_dates=["Timestamp"])["Timestamp"]
                stamps.update(pd.Timestamp(v) for v in col.dropna().tolist())
            except Exception as e:  # 資料檔壞掉不該讓服務掛掉
                logger.warning(f"時間軸載入失敗 ({path.name}): {type(e).__name__}: {e}")

        tl = sorted(stamps)
        _timeline_cache["key"] = key
        _timeline_cache["timeline"] = tl
        return tl


def parse_time(value) -> pd.Timestamp | None:
    """寬鬆解析時間字串；無法解析或空值回傳 None。"""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value
    if isinstance(value, datetime):
        return pd.Timestamp(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        ts = pd.Timestamp(text)
        return None if pd.isna(ts) else ts
    except Exception:
        logger.warning(f"無法解析時間: {value!r}")
        return None


def _index_at_or_before(tl: list[pd.Timestamp], ts: pd.Timestamp) -> int:
    """回傳 <= ts 的最後一個索引；若 ts 早於全部資料則回傳 0。"""
    return max(0, bisect.bisect_right(tl, ts) - 1)


def _position_for(tl: list[pd.Timestamp], ts: pd.Timestamp) -> float:
    """
    把時間換算成「時間軸索引空間」的浮點位置。
    例如 17:00 與 18:00 之間的一半 → 索引 2.5。smooth 模式用它讓每個
    資料間隔耗費相同的真實秒數，與間隔本身長短無關。
    """
    last = len(tl) - 1
    i = _index_at_or_before(tl, ts)
    if i >= last:
        return float(last)
    span = (tl[i + 1] - tl[i]).total_seconds()
    if span <= 0:
        return float(i)
    frac = (ts - tl[i]).total_seconds() / span
    return i + min(max(frac, 0.0), 1.0)


def _time_at_position(tl: list[pd.Timestamp], pos: float) -> pd.Timestamp:
    """_position_for 的反向運算：索引空間位置 → 實際時間。"""
    last = len(tl) - 1
    if pos >= last:
        return tl[last]
    i = int(pos)
    frac = pos - i
    if frac <= 0:
        return tl[i]
    return (tl[i] + (tl[i + 1] - tl[i]) * frac).floor("s")


def snap(ts: pd.Timestamp) -> pd.Timestamp:
    """將任意時間對齊到資料集中 <= ts 的最近時間點。"""
    tl = timeline()
    if not tl:
        return ts
    return tl[_index_at_or_before(tl, ts)]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"{name} 不是數字 ({raw!r})，改用預設 {default}")
        return default
    return value if value > 0 else default


# ---------------------------------------------------------------------------
# 單次請求 override
# ---------------------------------------------------------------------------

_override: ContextVar[pd.Timestamp | None] = ContextVar("sim_time_override", default=None)


@contextmanager
def override(value=None):
    """
    在此 context 內把模擬時間固定為 value（不影響全域時鐘）。
    value 為空時等於不做任何事，方便直接包在請求處理流程外層。
    """
    ts = parse_time(value)
    if ts is None:
        yield None
        return
    token = _override.set(ts)
    try:
        yield ts
    finally:
        _override.reset(token)


# ---------------------------------------------------------------------------
# 時鐘
# ---------------------------------------------------------------------------


class SimulationClock:
    """執行緒安全的模擬時鐘。時間由真實時間推導，不需背景 thread。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._prev_mode: str | None = None
        self.reset()

    # --- 設定 ---------------------------------------------------------------

    def reset(self) -> dict:
        """回到 .env / 環境變數定義的初始狀態。"""
        with self._lock:
            mode = (os.environ.get("SIM_CLOCK_MODE") or DEFAULT_MODE).strip().lower()
            if mode not in MODES:
                logger.warning(f"SIM_CLOCK_MODE={mode!r} 不支援，改用 {DEFAULT_MODE}")
                mode = DEFAULT_MODE

            self.mode = mode
            self.interval = _env_float("SIM_CLOCK_INTERVAL", DEFAULT_INTERVAL)
            self.speed = _env_float("SIM_CLOCK_SPEED", DEFAULT_SPEED)
            self.poll = _env_float("SIM_CLOCK_POLL", DEFAULT_POLL)
            self.loop = _env_bool("SIM_CLOCK_LOOP", DEFAULT_LOOP)
            self._prev_mode = None

            start = parse_time(os.environ.get("SIM_CLOCK_START")) or self.timeline_start()
            self._anchor(start)
            logger.info(
                f"模擬時鐘啟動: mode={self.mode} start={self._anchor_sim.strftime(TIME_FMT)} "
                f"interval={self.interval}s speed={self.speed}x loop={self.loop}"
            )
            return self.state()

    def configure(
        self,
        mode: str | None = None,
        sim_time=None,
        speed: float | None = None,
        interval: float | None = None,
        loop: bool | None = None,
        poll: float | None = None,
    ) -> dict:
        with self._lock:
            if mode is not None:
                normalized = str(mode).strip().lower()
                if normalized not in MODES:
                    raise ValueError(f"mode 必須是 {', '.join(MODES)} 之一，收到 {mode!r}")
                self.mode = normalized
                self._prev_mode = None
            if speed is not None:
                if float(speed) <= 0:
                    raise ValueError("speed 必須大於 0")
                self.speed = float(speed)
            if interval is not None:
                if float(interval) <= 0:
                    raise ValueError("interval 必須大於 0")
                self.interval = float(interval)
            if poll is not None:
                if float(poll) <= 0:
                    raise ValueError("poll 必須大於 0")
                self.poll = float(poll)
            if loop is not None:
                self.loop = bool(loop)

            target = parse_time(sim_time)
            if sim_time is not None and target is None:
                raise ValueError(f"無法解析 sim_time: {sim_time!r}")

            # 重新錨定：有指定就用指定時間，否則沿用當下模擬時間
            self._anchor(target if target is not None else self.now())
            return self.state()

    def advance(self, minutes: float | None = None, steps: int | None = None) -> dict:
        """相對前進 / 後退。steps 以資料集時間點為單位，minutes 以模擬分鐘為單位。"""
        with self._lock:
            current = self.now()
            if steps:
                tl = timeline()
                if tl:
                    idx = self._wrap_index(_index_at_or_before(tl, current) + int(steps), len(tl))
                    target = tl[idx]
                else:
                    target = current
            elif minutes:
                target = self._clamp(current + timedelta(minutes=float(minutes)))
            else:
                raise ValueError("請提供 minutes 或 steps")
            self._anchor(target)
            return self.state()

    def pause(self) -> dict:
        """凍結在當下模擬時間（記住原模式，供 resume 還原）。"""
        with self._lock:
            if self.mode != "fixed":
                self._prev_mode = self.mode
            self._anchor(self.now())
            self.mode = "fixed"
            return self.state()

    def resume(self) -> dict:
        with self._lock:
            if self.mode == "fixed":
                self.mode = self._prev_mode or DEFAULT_MODE
                self._prev_mode = None
                self._anchor(self.now())
            return self.state()

    # --- 查詢 ---------------------------------------------------------------

    def now(self) -> pd.Timestamp:
        """當下的模擬時間。"""
        forced = _override.get()
        if forced is not None:
            return forced

        with self._lock:
            mode = self.mode
            if mode == "fixed":
                return self._anchor_sim
            if mode == "latest":
                return self.timeline_end()

            elapsed = max(0.0, time.monotonic() - self._anchor_real)

            if mode == "playback":
                tl = timeline()
                if not tl:
                    return self._anchor_sim
                steps = int(elapsed // self.interval)
                idx = self._wrap_index(_index_at_or_before(tl, self._anchor_sim) + steps, len(tl))
                return tl[idx]

            if mode == "smooth":
                tl = timeline()
                if len(tl) < 2:
                    return self._anchor_sim
                last = len(tl) - 1
                pos = _position_for(tl, self._anchor_sim) + elapsed / self.interval
                pos = (pos % last) if self.loop else min(pos, float(last))
                return _time_at_position(tl, pos)

            # auto：連續時間
            return self._clamp(self._anchor_sim + timedelta(seconds=elapsed * self.speed))

    def resolve(self, explicit=None) -> pd.Timestamp:
        """有帶明確時間就用它，否則用當下模擬時間。"""
        ts = parse_time(explicit)
        return ts if ts is not None else self.now()

    def timeline_start(self) -> pd.Timestamp:
        tl = timeline()
        return tl[0] if tl else pd.Timestamp.now().floor("min")

    def timeline_end(self) -> pd.Timestamp:
        tl = timeline()
        return tl[-1] if tl else pd.Timestamp.now().floor("min")

    def next_change_in_seconds(self) -> float | None:
        """
        距離「跨越下一個資料時間點」還有幾秒。
        fixed / latest 回傳 None（時間不會動）。
        """
        if _override.get() is not None:
            return None
        with self._lock:
            if self.mode in {"fixed", "latest"}:
                return None

            elapsed = max(0.0, time.monotonic() - self._anchor_real)
            if self.mode == "playback":
                return round(self.interval - (elapsed % self.interval), 2)

            if self.mode == "smooth":
                tl = timeline()
                if len(tl) < 2:
                    return None
                last = len(tl) - 1
                pos = _position_for(tl, self._anchor_sim) + elapsed / self.interval
                pos = (pos % last) if self.loop else min(pos, float(last))
                if pos >= last:
                    return None
                return round(self.interval * (1 - (pos - int(pos))), 2)

            tl = timeline()
            current = self.now()
            future = [t for t in tl if t > current]
            if not future:
                return None
            return round((future[0] - current).total_seconds() / self.speed, 2)

    def suggested_poll_seconds(self) -> float | None:
        """
        建議前端多久抓一次。
        連續模式（smooth / auto）時間隨時在動 → 用固定的輪詢節奏；
        playback 只在跨資料點時變動 → 對齊下次變動；
        fixed / latest 回傳 None，前端可以慢慢輪。
        """
        if _override.get() is not None:
            return None
        with self._lock:
            if self.mode in {"fixed", "latest"}:
                return None
            if self.mode in CONTINUOUS_MODES:
                return self.poll
        return self.next_change_in_seconds()

    def state(self) -> dict:
        tl = timeline()
        current = self.now()
        forced = _override.get()
        with self._lock:
            return {
                "mode": "override" if forced is not None else self.mode,
                "configured_mode": self.mode,
                "is_overridden": forced is not None,
                "is_paused": self.mode == "fixed",
                "is_continuous": self.mode in CONTINUOUS_MODES,
                "sim_time": current.strftime(TIME_FMT),
                "sim_time_iso": current.isoformat(),
                "real_time": datetime.now().strftime(TIME_FMT),
                "speed": self.speed,
                "interval_seconds": self.interval,
                "loop": self.loop,
                "next_change_in_seconds": self.next_change_in_seconds(),
                "suggested_poll_seconds": self.suggested_poll_seconds(),
                "timeline_start": tl[0].strftime(TIME_FMT) if tl else None,
                "timeline_end": tl[-1].strftime(TIME_FMT) if tl else None,
                "timeline_size": len(tl),
                "timeline_index": _index_at_or_before(tl, current) if tl else None,
            }

    # --- 內部 ---------------------------------------------------------------

    def _anchor(self, sim_time: pd.Timestamp) -> None:
        self._anchor_sim = self._clamp(sim_time)
        self._anchor_real = time.monotonic()

    def _clamp(self, ts: pd.Timestamp) -> pd.Timestamp:
        """把時間限制在資料集範圍內；loop 模式下超出範圍會繞回。"""
        tl = timeline()
        if not tl:
            return ts
        start, end = tl[0], tl[-1]
        if start <= ts <= end:
            return ts

        span = (end - start).total_seconds()
        if span <= 0:
            return start
        if not self.loop:
            return start if ts < start else end
        offset = (ts - start).total_seconds() % span
        return start + timedelta(seconds=offset)

    def _wrap_index(self, idx: int, size: int) -> int:
        if size <= 0:
            return 0
        if self.loop:
            return idx % size
        return min(max(idx, 0), size - 1)


clock = SimulationClock()


# ---------------------------------------------------------------------------
# 模組層便利函式
# ---------------------------------------------------------------------------


def now() -> pd.Timestamp:
    return clock.now()


def resolve(explicit=None) -> pd.Timestamp:
    return clock.resolve(explicit)


def now_str() -> str:
    return clock.now().strftime(TIME_FMT)


def state() -> dict:
    return clock.state()
