import { useCallback, useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Clock,
  Gauge,
  Pause,
  Play,
  Radio,
  RotateCcw,
  Wifi,
  WifiOff,
} from "lucide-react";
import { cn } from "../lib/utils";

/**
 * 模擬時間軸控制列
 *
 * 後端早就提供 /api/clock、/api/timeline、advance/pause/resume/reset，
 * 但前端沒有任何入口，Demo 時無法暫停、回放或跳到事故時間點。
 * 這一列把時鐘完整交到指揮官手上。
 *
 * 時鐘指令不一定會改變模擬時間（例如暫停），這種情況後端不會推播，
 * 所以每次下指令後都主動 refresh() 一次路網狀態。
 */

const INTERVAL_OPTIONS = [
  { value: 1, label: "1 秒/格" },
  { value: 3, label: "3 秒/格" },
  { value: 5, label: "5 秒/格" },
  { value: 10, label: "10 秒/格" },
];

async function postClock(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export default function TimelineControl({ clock, dataMode, transport, onChanged }) {
  const [timeline, setTimeline] = useState([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // 時間軸是資料集決定的靜態清單，載入一次就好
  useEffect(() => {
    let cancelled = false;
    fetch("/api/timeline")
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setTimeline(d.timestamps || []);
      })
      .catch(() => {
        if (!cancelled) setTimeline([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const run = useCallback(
    async (action) => {
      setBusy(true);
      setFailed(false);
      try {
        await action();
        await onChanged?.();
      } catch {
        setFailed(true);
      } finally {
        setBusy(false);
      }
    },
    [onChanged],
  );

  const index = clock?.timeline_index ?? 0;
  const total = clock?.timeline_size ?? timeline.length;
  const playing = Boolean(clock?.is_playing);
  const paused = Boolean(clock?.is_paused);
  const simTime = clock?.sim_time || "";
  const frozen = (clock?.active_freeze_count ?? 0) > 0;

  const jumpTo = (value) =>
    run(() => postClock("/api/clock", { sim_time: timeline[Number(value)] }));

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] px-4 py-3 space-y-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <Clock className="w-4 h-4 text-[var(--primary)] shrink-0" />
          <span className="text-sm font-semibold shrink-0">模擬時間</span>
          <span className="text-sm font-mono text-[var(--foreground)]">{simTime || "—"}</span>
          {total > 0 && (
            <span className="text-xs text-[var(--muted-foreground)]">
              第 {index + 1} / {total} 格
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            onClick={() => run(() => postClock("/api/clock/advance", { steps: -1 }))}
            disabled={busy || frozen}
            aria-label="上一個時間點"
            title="上一個時間點"
            className="p-1.5 rounded-sm bg-[var(--muted)] hover:bg-[var(--accent)] text-[var(--muted-foreground)] transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>

          <button
            type="button"
            onClick={() =>
              run(() => postClock(playing ? "/api/clock/pause" : "/api/clock/resume"))
            }
            disabled={busy || frozen}
            aria-label={playing ? "暫停時間推進" : "繼續播放"}
            title={playing ? "暫停時間推進" : "繼續播放"}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-sm bg-[var(--primary)] text-[var(--primary-foreground)] text-xs font-medium hover:opacity-90 transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            {playing ? "暫停" : "播放"}
          </button>

          <button
            type="button"
            onClick={() => run(() => postClock("/api/clock/advance", { steps: 1 }))}
            disabled={busy || frozen}
            aria-label="下一個時間點"
            title="下一個時間點"
            className="p-1.5 rounded-sm bg-[var(--muted)] hover:bg-[var(--accent)] text-[var(--muted-foreground)] transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            <ChevronRight className="w-4 h-4" />
          </button>

          <button
            type="button"
            onClick={() => run(() => postClock("/api/clock/reset"))}
            disabled={busy || frozen}
            aria-label="回到時間軸起點"
            title="回到時間軸起點"
            className="p-1.5 rounded-sm bg-[var(--muted)] hover:bg-[var(--accent)] text-[var(--muted-foreground)] transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>

          <label className="sr-only" htmlFor="clock-interval">
            每格停留秒數
          </label>
          <select
            id="clock-interval"
            value={clock?.interval_seconds ?? 1}
            onChange={(e) =>
              run(() => postClock("/api/clock", { interval: Number(e.target.value) }))
            }
            disabled={busy || frozen}
            title="每格停留秒數"
            className="bg-[var(--muted)] border border-[var(--border)] rounded-sm text-xs px-2 py-1.5 text-[var(--muted-foreground)] disabled:opacity-50 focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            {INTERVAL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => run(() => postClock("/api/clock", { loop: !clock?.loop }))}
            disabled={busy || frozen}
            aria-pressed={Boolean(clock?.loop)}
            title="播完後從頭再播"
            className={cn(
              "px-2.5 py-1.5 rounded-sm text-xs border transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
              clock?.loop
                ? "bg-[var(--accent)] text-[var(--accent-foreground)] border-[var(--primary)] font-medium"
                : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)] hover:bg-[var(--accent)]",
            )}
          >
            循環
          </button>
        </div>
      </div>

      {/* 時間軸拉桿：可直接跳到事故發生的時間點 */}
      {total > 1 && (
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono text-[var(--muted-foreground)] shrink-0">
            {timeline[0]?.slice(11) || ""}
          </span>
          <input
            type="range"
            min={0}
            max={Math.max(0, timeline.length - 1)}
            value={Math.min(index, Math.max(0, timeline.length - 1))}
            onChange={(e) => jumpTo(e.target.value)}
            disabled={busy || frozen || timeline.length === 0}
            aria-label="跳到指定時間點"
            className="flex-1 accent-[var(--primary)] disabled:opacity-50"
          />
          <span className="text-xs font-mono text-[var(--muted-foreground)] shrink-0">
            {timeline[timeline.length - 1]?.slice(11) || ""}
          </span>
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap text-xs text-[var(--muted-foreground)]">
        <span className="flex items-center gap-1">
          {transport === "websocket" ? (
            <>
              <Radio className="w-3 h-3 text-[var(--status-success)]" />
              WebSocket 推播
            </>
          ) : transport === "polling" ? (
            <>
              <Wifi className="w-3 h-3 text-[var(--status-warning)]" />
              輪詢模式
            </>
          ) : (
            <>
              <WifiOff className="w-3 h-3 text-[var(--status-error)]" />
              連線中斷
            </>
          )}
        </span>

        <span className="flex items-center gap-1" title="資料切片語意">
          <Gauge className="w-3 h-3" />
          {dataMode === "asof"
            ? "as-of（僅使用當下與過去的量測）"
            : dataMode === "exact"
              ? "exact（單一時間點切片）"
              : "interpolate（量測點之間線性插值）"}
        </span>

        {paused && !frozen && <span className="text-[var(--status-warning)]">已暫停</span>}
        {frozen && (
          <span className="text-[var(--status-warning)]">
            事件處置進行中，時鐘已凍結
          </span>
        )}
        {failed && <span className="text-[var(--status-error)]">時鐘指令失敗，請重試</span>}
      </div>
    </div>
  );
}
