import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Pause, Play, Radio } from "lucide-react";
import { cn } from "../lib/utils";
import { SKIP_MINUTES } from "../lib/useStreamClock";

const MINUTE_MS = 60000;
// 刻度密度：每個標籤大約佔這麼寬，用來挑選刻度間隔
const PX_PER_LABEL = 92;
const TICK_CHOICES_MINUTES = [1, 2, 5, 10, 15, 30, 60, 120, 180];

function timeLabel(ms) {
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function pickTickMinutes(windowMinutes, width) {
  const target = windowMinutes / Math.max(1, Math.floor(width / PX_PER_LABEL));
  return TICK_CHOICES_MINUTES.find((m) => m >= target) ?? TICK_CHOICES_MINUTES.at(-1);
}

/**
 * StreamTimeline — 監控主機風格的時間軸
 *
 * 時間軸最右邊永遠是直播點：
 *   - LIVE：游標貼在最右邊，刻度隨時間往左捲動
 *   - 拖動時間軸：切換成回看（playback），游標停在該時間，畫面顯示那個時間的路網
 *     資料（上層以 /api/status?ts= 取回，不影響其他連線）
 *   - 拖回最右邊或按 LIVE：回到直播
 *
 * stream：useStreamClock() 的回傳值
 */
export default function StreamTimeline({ stream, className = "" }) {
  const {
    ready = false,
    error = "",
    timeline = [],
    offsetMs = 0,
    maxRewindMs = 0,
    windowMs = 60 * MINUTE_MS,
    windowMinutes = 60,
    playheadStamp = "",
    behindMinutes = 0,
    spanMs = MINUTE_MS,
    isLive = false,
    isPlaying = false,
    datasetMsAtOffset,
    seekToOffset,
    skipMinutes,
    togglePlay,
    goLive,
  } = stream || {};

  const railRef = useRef(null);
  const [width, setWidth] = useState(0);
  const [dragging, setDragging] = useState(false);

  // 量測軌道寬度，用來換算像素與時間
  useLayoutEffect(() => {
    const el = railRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  // x（軌道內像素）↔ 落後直播多久。最右邊 = 直播點
  const offsetAtX = useCallback(
    (x) => ((width - Math.max(0, Math.min(x, width))) / Math.max(1, width)) * windowMs,
    [width, windowMs],
  );
  const xForOffset = useCallback(
    (ms) => width - (ms / windowMs) * width,
    [width, windowMs],
  );

  const seekFromEvent = useCallback(
    (event) => {
      const rail = railRef.current;
      if (!rail || !seekToOffset) return;
      const rect = rail.getBoundingClientRect();
      seekToOffset(offsetAtX(event.clientX - rect.left));
    },
    [offsetAtX, seekToOffset],
  );

  const onPointerDown = (event) => {
    if (!ready) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDragging(true);
    seekFromEvent(event);
  };

  const onPointerMove = (event) => {
    if (!dragging) return;
    seekFromEvent(event);
  };

  const endDrag = (event) => {
    if (!dragging) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    setDragging(false);
  };

  // 快捷鍵處理器只註冊一次，透過 ref 取用最新的操作函式
  const actions = useRef({ skipMinutes, goLive });
  actions.current = { skipMinutes, goLive };
  const tickMinutes = pickTickMinutes(windowMinutes, width || 800);

  // [ 往回看、] 往直播方向前進、L 回到 LIVE
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = e.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.target?.isContentEditable) return;
      if (e.key === "[") {
        e.preventDefault();
        actions.current.skipMinutes?.(-SKIP_MINUTES);
      } else if (e.key === "]") {
        e.preventDefault();
        actions.current.skipMinutes?.(SKIP_MINUTES);
      } else if (e.key === "l" || e.key === "L") {
        e.preventDefault();
        actions.current.goLive?.();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const onKeyDownRail = (e) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      skipMinutes?.(-SKIP_MINUTES);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      skipMinutes?.(SKIP_MINUTES);
    } else if (e.key === "Home") {
      e.preventDefault();
      seekToOffset?.(maxRewindMs);
    } else if (e.key === "End") {
      e.preventDefault();
      goLive?.();
    }
  };

  // 刻度：從直播點往回，每 tickMinutes 一格，並對齊到整齊的時間值
  const ticks = [];
  if (ready && width > 0 && datasetMsAtOffset) {
    const tickMs = tickMinutes * MINUTE_MS;
    const liveMs = datasetMsAtOffset(0);
    // 對齊到最靠近直播點、且不晚於直播點的整齊時間
    const firstOffset = liveMs - Math.floor(liveMs / tickMs) * tickMs;
    for (let ms = firstOffset; ms <= windowMs + 1; ms += tickMs) {
      ticks.push({ offset: ms, x: xForOffset(ms), at: datasetMsAtOffset(ms) });
    }
  }

  // 已播出（可回看）的區段寬度
  const airedX = ready ? xForOffset(maxRewindMs) : width;
  const cursorX = ready ? xForOffset(offsetMs) : width;

  return (
    <div
      className={cn(
        "bg-[var(--card)] rounded-lg border border-[var(--border)] px-4 py-3",
        className,
      )}
    >
      {/* 上排：目前時間與播放控制（回看 15 分 / 暫停 / 前進 15 分 / LIVE） */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 mb-2">
        <div className="flex items-baseline gap-2 min-w-0">
          <span
            className={cn(
              "text-lg font-semibold font-mono tabular-nums",
              isLive ? "text-[var(--status-success)]" : "text-[var(--foreground)]",
            )}
          >
            {playheadStamp ? playheadStamp.slice(11, 16) : "--:--"}
          </span>
          <span className="text-xs text-[var(--muted-foreground)] font-mono">
            {playheadStamp ? playheadStamp.slice(0, 10) : ""}
          </span>
          {!isLive && behindMinutes > 0 && (
            <span className="text-xs text-[var(--muted-foreground)]">
              落後 {behindMinutes} 分
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 ml-auto">
          {/* 播放控制：回看 15 分 → 暫停/播放 → 前進 15 分 */}
          <div className="flex items-center gap-1">
            <StepButton
              label={`回看 ${SKIP_MINUTES} 分鐘`}
              hint="["
              onClick={() => skipMinutes?.(-SKIP_MINUTES)}
              disabled={!ready || offsetMs >= maxRewindMs}
            >
              <ChevronLeft className="w-4 h-4" />
              {SKIP_MINUTES}分
            </StepButton>

            <button
              type="button"
              onClick={() => togglePlay?.()}
              disabled={!ready}
              title={isPlaying ? "暫停" : "繼續播放"}
              aria-label={isPlaying ? "暫停" : "繼續播放"}
              className={cn(
                "flex items-center justify-center w-8 h-7 rounded-md border transition",
                "focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                "disabled:opacity-50 disabled:pointer-events-none",
                "bg-[var(--card)] border-[var(--border)] text-[var(--muted-foreground)]",
                "hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]",
              )}
            >
              {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            </button>

            <StepButton
              label={`往直播方向前進 ${SKIP_MINUTES} 分鐘`}
              hint="]"
              onClick={() => skipMinutes?.(SKIP_MINUTES)}
              disabled={!ready || offsetMs <= 0}
            >
              {SKIP_MINUTES}分
              <ChevronRight className="w-4 h-4" />
            </StepButton>
          </div>

          <button
            type="button"
            onClick={() => goLive?.()}
            disabled={!ready}
            title="回到 LIVE（L）"
            aria-label="回到 LIVE"
            aria-pressed={isLive}
            className={cn(
              "flex items-center gap-1.5 h-7 px-2.5 rounded-md border text-xs font-semibold transition",
              "focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
              "disabled:opacity-50 disabled:pointer-events-none",
              isLive
                ? "bg-[var(--status-running)]/15 border-[var(--status-running)]/40 text-[var(--status-success)]"
                : "bg-[var(--card)] border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]",
            )}
          >
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                isLive ? "bg-[var(--status-running)] animate-pulse" : "bg-[var(--muted-foreground)]",
              )}
            />
            <Radio className="w-3.5 h-3.5" />
            LIVE
          </button>
        </div>
      </div>

      {/* 時間軸軌道：拖動即進入回看 */}
      <div
        ref={railRef}
        role="slider"
        tabIndex={ready ? 0 : -1}
        aria-label="串流時間軸，拖動以回看較早的時間"
        aria-valuemin={0}
        aria-valuemax={Math.round(windowMs / MINUTE_MS)}
        aria-valuenow={Math.round((windowMs - offsetMs) / MINUTE_MS)}
        aria-valuetext={isLive ? `LIVE ${playheadStamp}` : playheadStamp}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={onKeyDownRail}
        className={cn(
          "relative h-14 select-none touch-none rounded-md bg-[var(--muted)]",
          "border border-[var(--border)] overflow-hidden",
          "focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
          ready ? (dragging ? "cursor-grabbing" : "cursor-pointer") : "opacity-60",
        )}
      >
        {/* 已播出、可回看的區段 */}
        <div
          className="absolute inset-y-0 bg-[var(--card)]"
          style={{ left: `${Math.max(0, airedX)}px`, right: 0 }}
        />

        {/* 刻度與時間標籤 */}
        {ticks.map((tick) => (
          <div
            key={tick.offset}
            className="absolute top-0 bottom-0 flex flex-col items-start"
            style={{ left: `${tick.x}px` }}
          >
            <span className="absolute top-0 h-2.5 w-px bg-[var(--border)]" />
            <span className="absolute top-3 -translate-x-1/2 text-[10px] font-mono tabular-nums text-[var(--muted-foreground)] whitespace-nowrap">
              {timeLabel(tick.at)}
            </span>
            <span className="absolute bottom-0 h-2 w-px bg-[var(--border)]" />
          </div>
        ))}

        {/* 資料集實際有量測的時間點 */}
        <div className="absolute inset-x-0 bottom-2 h-2">
          {ready &&
            width > 0 &&
            timeline.map((stamp) => {
              const at = new Date(stamp.replace(" ", "T")).getTime();
              const liveAt = datasetMsAtOffset(0);
              let back = liveAt - at;
              if (back < 0) back += spanMs;
              if (back > windowMs) return null;
              return (
                <span
                  key={stamp}
                  className="absolute top-0 h-2 w-0.5 rounded-full bg-[var(--chart-2)]/60"
                  style={{ left: `${xForOffset(back)}px` }}
                  title={stamp}
                />
              );
            })}
        </div>

        {/* 游標：LIVE 時永遠貼在最右邊 */}
        <div
          className="absolute inset-y-0 w-0.5 bg-[var(--status-error)] pointer-events-none"
          style={{ left: `${Math.min(Math.max(cursorX, 0), Math.max(0, width - 2))}px` }}
        >
          <span className="absolute -top-0.5 left-1/2 -translate-x-1/2 w-2 h-2 rounded-full bg-[var(--status-error)]" />
        </div>

        {/* 最右緣的 LIVE 標記 */}
        {ready && (
          <span
            className={cn(
              "absolute top-1 right-1 text-[10px] font-semibold px-1 rounded-sm",
              isLive
                ? "bg-[var(--status-running)] text-[var(--primary-foreground)]"
                : "bg-[var(--muted)] text-[var(--muted-foreground)]",
            )}
          >
            LIVE
          </span>
        )}
      </div>

      {!ready && !error && (
        <div className="mt-1 text-xs text-[var(--muted-foreground)]">等待串流資料</div>
      )}
      {error && <div className="mt-1 text-xs text-[var(--status-error)]">{error}</div>}
    </div>
  );
}

function StepButton({ label, hint, onClick, disabled, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={hint ? `${label}（${hint}）` : label}
      aria-label={label}
      className={cn(
        "flex items-center h-7 px-1.5 rounded-md border text-xs font-medium tabular-nums transition",
        "focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
        "disabled:opacity-50 disabled:pointer-events-none",
        "bg-[var(--card)] border-[var(--border)] text-[var(--muted-foreground)]",
        "hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]",
      )}
    >
      {children}
    </button>
  );
}
