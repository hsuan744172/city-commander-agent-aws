import { ShieldAlert, Check } from "lucide-react";
import { cn } from "../lib/utils";

function sortByThreat(segments) {
  const order = { A: 0, B: 1, Normal: 2 };
  return [...segments].sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3));
}

function cardStyle(level, inChart) {
  if (inChart) return "border-[var(--status-info)] bg-[var(--status-info)]/10 ring-1 ring-[var(--status-info)]/30";
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

export default function ThreatGrid({ segments, timestamp, onAddToChart, chartSegmentIds }) {
  const sorted = sortByThreat(segments);
  const criticalCount = sorted.filter((s) => s.level === "A").length;
  const congestedCount = sorted.filter((s) => s.level === "B").length;

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-5 h-5 text-[var(--primary)]" />
          <h2 className="text-sm font-semibold">即時路網監測</h2>
          <span className="text-xs text-[var(--muted-foreground)]">點擊卡片加入趨勢圖</span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {criticalCount > 0 && (
            <span className="bg-[var(--status-error)] text-[var(--primary-foreground)] px-2.5 py-0.5 rounded-full font-bold animate-pulse">
              {criticalCount} 癱瘓
            </span>
          )}
          {congestedCount > 0 && (
            <span className="bg-[var(--status-warning)] text-[var(--primary-foreground)] px-2.5 py-0.5 rounded-full font-bold">
              {congestedCount} 壅擠
            </span>
          )}
          <span className="text-[var(--muted-foreground)]">{timestamp}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
        {sorted.map((seg) => {
          const pct = Math.round(seg.saturation_score * 100);
          const status = statusLabel(seg.level);
          const inChart = chartSegmentIds?.includes(seg.segment_id);

          return (
            <div
              key={seg.segment_id}
              onClick={() => onAddToChart?.(seg)}
              className={cn(
                "rounded-md border p-3 cursor-pointer transition hover:scale-[1.02] active:scale-95",
                cardStyle(seg.level, inChart)
              )}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium truncate">{seg.road_name}</span>
                <div className="flex items-center gap-1">
                  {inChart && <Check className="w-3 h-3 text-[var(--status-info)]" />}
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded-sm font-bold", status.cls)}>
                    {status.text}
                  </span>
                </div>
              </div>

              <div className="w-full bg-[var(--muted)] rounded-full h-2 mb-2">
                <div className={cn("h-2 rounded-full transition-all", barColor(seg.level))} style={{ width: `${Math.min(pct, 100)}%` }} />
              </div>

              <div className="flex items-center justify-between text-[11px]">
                <span className={cn(
                  "font-bold",
                  seg.level === "A" ? "text-[var(--status-error)]" : seg.level === "B" ? "text-[var(--status-warning)]" : "text-[var(--status-success)]"
                )}>{pct}%</span>
                <span className="text-[var(--muted-foreground)]">{seg.avg_speed} km/h</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
