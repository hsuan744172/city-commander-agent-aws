import { useEffect, useRef } from "react";
import { ShieldAlert } from "lucide-react";
import { cn } from "../lib/utils";

function sortByThreat(segments) {
  const order = { A: 0, B: 1, Normal: 2 };
  return [...segments].sort(
    (a, b) =>
      (order[a.level] ?? 3) - (order[b.level] ?? 3) || b.saturation_score - a.saturation_score,
  );
}

function cardStyle(level) {
  if (level === "A") return "border-[var(--status-error)]/60 bg-[var(--status-error)]/10";
  if (level === "B") return "border-[var(--status-warning)]/50 bg-[var(--status-warning)]/10";
  return "border-[var(--border)] bg-[var(--secondary)]";
}

function barColor(level) {
  if (level === "A") return "bg-[var(--status-error)]";
  if (level === "B") return "bg-[var(--status-warning)]";
  return "bg-[var(--status-success)]";
}

function statusLabel(level) {
  if (level === "A") return { text: "癱瘓", cls: "bg-[var(--status-error)] text-[var(--primary-foreground)]" };
  if (level === "B") return { text: "壅擠", cls: "bg-[var(--status-warning)] text-[var(--primary-foreground)]" };
  return { text: "正常", cls: "bg-[var(--status-success)] text-[var(--primary-foreground)]" };
}

/**
 * ThreatGrid — 路段事件小卡，作為地圖右側的側欄清單
 * 高度與地圖對齊，卡片依威脅等級排序，超出範圍可捲動
 * onSelect：點擊小卡時回傳該路段（跳往事件處置與建議書）
 * selectedSegmentId：目前聚焦路段，對應小卡會 highlight 並自動捲入視野
 */
export default function ThreatGrid({
  segments,
  timestamp,
  onSelect,
  selectedSegmentId = null,
  className = "",
}) {
  const sorted = sortByThreat(segments);
  const criticalCount = sorted.filter((s) => s.level === "A").length;
  const congestedCount = sorted.filter((s) => s.level === "B").length;
  const cardRefs = useRef({});

  useEffect(() => {
    if (!selectedSegmentId) return;
    cardRefs.current[selectedSegmentId]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedSegmentId]);

  return (
    <div
      className={cn(
        "bg-[var(--card)] rounded-lg border border-[var(--border)] p-3 flex flex-col",
        className,
      )}
    >
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div className="flex items-center gap-1.5">
          <ShieldAlert className="w-4 h-4 text-[var(--primary)]" />
          <h2 className="text-sm font-semibold">即時路網監測</h2>
        </div>
        <div className="flex items-center gap-1.5 text-xs">
          {criticalCount > 0 && (
            <span className="bg-[var(--status-error)] text-[var(--primary-foreground)] px-2 py-0.5 rounded-full font-bold animate-pulse">
              {criticalCount} 癱瘓
            </span>
          )}
          {congestedCount > 0 && (
            <span className="bg-[var(--status-warning)] text-[var(--primary-foreground)] px-2 py-0.5 rounded-full font-bold">
              {congestedCount} 壅擠
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 text-xs text-[var(--muted-foreground)] mb-2 shrink-0">
        {timestamp && <span>資料時間 {timestamp}</span>}
        {onSelect && <span>點擊查看處置建議</span>}
      </div>

      <div className="flex-1 overflow-y-auto space-y-2 pr-0.5">
        {sorted.map((seg) => {
          const pct = Math.round(seg.saturation_score * 100);
          const status = statusLabel(seg.level);

          return (
            <div
              key={seg.segment_id}
              ref={(el) => {
                cardRefs.current[seg.segment_id] = el;
              }}
              role={onSelect ? "button" : undefined}
              tabIndex={onSelect ? 0 : undefined}
              aria-label={
                onSelect
                  ? `${seg.road_name} ${status.text}，飽和度 ${pct}%，查看事件處置與建議書`
                  : undefined
              }
              onClick={onSelect ? () => onSelect(seg) : undefined}
              onKeyDown={
                onSelect
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect(seg);
                      }
                    }
                  : undefined
              }
              className={cn(
                "rounded-md border p-2.5",
                cardStyle(seg.level),
                onSelect &&
                  "cursor-pointer transition hover:brightness-[0.97] active:scale-[0.99] focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                seg.segment_id === selectedSegmentId && "ring-2 ring-[var(--accent)]",
              )}
            >
              <div className="flex items-center justify-between gap-1 mb-1.5">
                <span className="text-xs font-medium truncate">{seg.road_name}</span>
                <div className="flex items-center gap-1 shrink-0">
                  {/* SOP 第 1 條只有這兩段達級別才啟動應變，其餘僅燈號顯示 */}
                  {seg.is_trigger_segment && (
                    <span
                      title="SOP 第 1 條城市應變觸發路段"
                      className="text-[9px] px-1 py-0.5 rounded-sm font-bold bg-[var(--accent)] text-[var(--accent-foreground)]"
                    >
                      觸發
                    </span>
                  )}
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded-sm font-bold", status.cls)}>
                    {status.text}
                  </span>
                </div>
              </div>

              <div className="w-full bg-[var(--muted)] rounded-full h-2 mb-1.5">
                <div
                  className={cn("h-2 rounded-full transition-all", barColor(seg.level))}
                  style={{ width: `${Math.min(pct, 100)}%` }}
                />
              </div>

              <div className="flex items-center justify-between text-[11px]">
                <span
                  className={cn(
                    "font-bold",
                    seg.level === "A"
                      ? "text-[var(--status-error)]"
                      : seg.level === "B"
                        ? "text-[var(--status-warning)]"
                        : "text-[var(--status-success)]",
                  )}
                >
                  {pct}%
                </span>
                <span className="text-[var(--muted-foreground)]">{seg.avg_speed} km/h</span>
              </div>
            </div>
          );
        })}

        {sorted.length === 0 && (
          <div className="text-xs text-[var(--muted-foreground)] py-6 text-center">等待路網資料</div>
        )}
      </div>
    </div>
  );
}
