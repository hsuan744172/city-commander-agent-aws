import { useCallback, useEffect, useRef, useState } from "react";

// 與後端重新對時的間隔；其餘時間由前端自行推進，避免每分鐘都打一次 API。
const RESYNC_MS = 30000;
const TICK_MS = 1000;
const MINUTE_MS = 60000;

/** 時間軸一次顯示多長（分鐘）。同時決定最多能往回看多久。 */
export const WINDOW_MINUTES = 60;

/** 前後跳一次的分鐘數。 */
export const SKIP_MINUTES = 15;

function toMs(stamp) {
  // "2026-05-20 21:30" → epoch ms（當成本地時間，只用於相對計算）
  return stamp ? new Date(stamp.replace(" ", "T")).getTime() : 0;
}

export function toStamp(ms) {
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/**
 * 串流播放器時鐘（GET /api/stream）
 *
 * 後端的模擬時間以實際時間 1:1 前進，跑完資料集再從頭播一次，等於一路不停的直播
 * 訊號。這個 hook 讓前端像有 DVR 的監控時間軸：
 *   - LIVE：貼著直播點，游標永遠在時間軸最右邊
 *   - 回看（playback）：落後直播一段時間，播放速度與直播同步
 *   - 暫停：播放頭停住，落後時間持續累積
 *
 * 位置一律以「落後直播多久」(offsetMs) 表示，資料循環播放時仍然對得上；
 * 能往回看的範圍等於時間軸視窗長度（WINDOW_MINUTES）。
 * 播放頭時間只用在 /api/status?ts=，不會動到後端全域時鐘。
 */
export default function useStreamClock() {
  const [stream, setStream] = useState({
    timeline: [],
    startMs: 0,
    spanMs: MINUTE_MS,
    loop: true,
    liveSpeed: 1,
    ready: false,
  });
  const [error, setError] = useState("");
  // 落後直播多久（毫秒）；0 代表 LIVE
  const [offset, setOffset] = useState(0);
  const [isPlaying, setPlaying] = useState(true);
  // 本地推進基準：從這一刻的直播進度開始，用真實時間往前推
  const anchor = useRef({ elapsedMs: 0, at: 0, liveSpeed: 1 });
  const lastElapsed = useRef(0);
  // 直播已播出的總時長。刻意放在 state 而不是每次 render 重算：
  // 重算會讓「播放頭推進」的更新自己觸發下一次更新，形成無窮迴圈。
  const [liveElapsedMs, setLiveElapsedMs] = useState(0);

  const sync = useCallback(async () => {
    try {
      const res = await fetch("/api/stream");
      const data = await res.json();
      const timeline = Array.isArray(data.timeline) ? data.timeline : [];
      if (timeline.length === 0 || !data.live_time) {
        setError("後端尚未提供時間軸資料");
        return;
      }
      const spanMs = Math.max(Number(data.span_minutes) || 0, 1) * MINUTE_MS;
      const liveSpeed = Number(data.speed) > 0 ? Number(data.speed) : 1;
      const cycle = Number(data.cycle) || 0;
      // 直播已播出的總時長（含前幾輪），用來對齊本地推算
      const elapsedMs = cycle * spanMs + (Number(data.live_progress_minutes) || 0) * MINUTE_MS;

      anchor.current = { elapsedMs, at: performance.now(), liveSpeed };
      lastElapsed.current = elapsedMs;
      setLiveElapsedMs(elapsedMs);
      setError("");
      setStream({
        timeline,
        startMs: toMs(timeline[0]),
        spanMs,
        loop: Boolean(data.loop),
        liveSpeed,
        ready: true,
      });
    } catch {
      setError("無法連線後端串流");
    }
  }, []);

  useEffect(() => {
    sync();
    const timer = setInterval(sync, RESYNC_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") sync();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [sync]);

  const { startMs, spanMs, ready } = stream;
  const windowMs = WINDOW_MINUTES * MINUTE_MS;

  // 可回看範圍：不超過視窗長度，也不超過一整輪資料。循環播放時整份資料集都算
  // 「播過了」，所以剛啟動也能往回看（會落到上一輪的同一段時間）。
  const airedMs = stream.loop ? spanMs - MINUTE_MS : liveElapsedMs;
  const maxRewindMs = ready ? Math.max(0, Math.min(windowMs, airedMs)) : 0;

  // 給計時器讀取最新設定，計時器本身只註冊一次
  const pace = useRef({ isPlaying, maxRewindMs });
  pace.current = { isPlaying, maxRewindMs };

  // 每秒推進一次：更新直播位置，並依播放狀態調整播放頭落後多久
  //   播放中 → 落後時間不變（與直播同速，LIVE 就一直貼著直播點）
  //   暫停   → 播放頭原地不動，落後時間持續累積
  useEffect(() => {
    if (!ready) return;
    const advance = () => {
      const now =
        anchor.current.elapsedMs +
        Math.max(0, performance.now() - anchor.current.at) * anchor.current.liveSpeed;
      const advanced = now - lastElapsed.current;
      lastElapsed.current = now;
      setLiveElapsedMs(now);
      if (advanced <= 0) return;
      const { isPlaying: playing, maxRewindMs: limit } = pace.current;
      if (playing) return;
      setOffset((current) => Math.max(0, Math.min(current + advanced, limit)));
    };
    const timer = setInterval(advance, TICK_MS);
    return () => clearInterval(timer);
  }, [ready]);

  const offsetMs = Math.min(offset, maxRewindMs);
  const isLive = offsetMs < MINUTE_MS && isPlaying;
  const liveProgressMs = stream.loop ? liveElapsedMs % spanMs : Math.min(liveElapsedMs, spanMs);

  /** 落後 offsetMs 時，對應到資料集的哪個時間（毫秒）。 */
  const datasetMsAtOffset = useCallback(
    (ms) => {
      const progress = stream.loop
        ? (((liveProgressMs - ms) % spanMs) + spanMs) % spanMs
        : Math.max(0, liveProgressMs - ms);
      return startMs + progress;
    },
    [stream.loop, liveProgressMs, spanMs, startMs],
  );

  const stampAtOffset = useCallback((ms) => toStamp(datasetMsAtOffset(ms)), [datasetMsAtOffset]);

  /** 跳到「落後直播 ms」的位置；落到最右邊（0）就回到 LIVE。 */
  const seekToOffset = useCallback(
    (ms) => {
      if (!ready) return;
      const next = Math.max(0, Math.min(ms, maxRewindMs));
      setOffset(next);
      if (next < MINUTE_MS) setPlaying(true);
    },
    [ready, maxRewindMs],
  );

  /** 相對移動：minutes > 0 往直播方向前進，< 0 往回看。 */
  const skipMinutes = useCallback(
    (minutes) => seekToOffset(offsetMs - minutes * MINUTE_MS),
    [seekToOffset, offsetMs],
  );

  const goLive = useCallback(() => {
    setOffset(0);
    setPlaying(true);
  }, []);

  const togglePlay = useCallback(() => setPlaying((playing) => !playing), []);

  return {
    ready,
    error,
    loop: stream.loop,
    liveSpeed: stream.liveSpeed,
    timeline: stream.timeline,
    // 位置
    offsetMs,
    maxRewindMs,
    windowMs,
    windowMinutes: WINDOW_MINUTES,
    playheadStamp: ready ? stampAtOffset(offsetMs) : "",
    liveStamp: ready ? stampAtOffset(0) : "",
    behindMinutes: Math.round(offsetMs / MINUTE_MS),
    cycle: spanMs > 0 ? Math.floor(liveElapsedMs / spanMs) : 0,
    spanMs,
    // 狀態
    isLive,
    isPlaying,
    // 換算與控制
    datasetMsAtOffset,
    stampAtOffset,
    seekToOffset,
    skipMinutes,
    togglePlay,
    goLive,
  };
}
