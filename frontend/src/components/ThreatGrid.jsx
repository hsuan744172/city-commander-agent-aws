import { ShieldAlert, Plus, Check } from "lucide-react";

function sortByThreat(segments) {
  const order = { A: 0, B: 1, Normal: 2 };
  return [...segments].sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3));
}

function cardStyle(level, inChart) {
  if (inChart) return "border-blue-500/60 bg-blue-950/30 ring-1 ring-blue-500/30";
  if (level === "A") return "border-red-500/60 bg-red-950/40";
  if (level === "B") return "border-yellow-500/50 bg-yellow-950/30";
  return "border-gray-700 bg-gray-800/50";
}

function barColor(level) {
  if (level === "A") return "bg-red-500";
  if (level === "B") return "bg-yellow-400";
  return "bg-green-500";
}

function statusLabel(level) {
  if (level === "A") return { text: "癱瘓", cls: "bg-red-600 text-red-100" };
  if (level === "B") return { text: "壅擠", cls: "bg-yellow-500 text-yellow-900" };
  return { text: "正常", cls: "bg-green-600 text-green-100" };
}

export default function ThreatGrid({ segments, timestamp, onAddToChart, chartSegmentIds }) {
  const sorted = sortByThreat(segments);
  const criticalCount = sorted.filter((s) => s.level === "A").length;
  const congestedCount = sorted.filter((s) => s.level === "B").length;

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-5 h-5 text-blue-400" />
          <h2 className="text-sm font-semibold text-gray-200">即時路網監測</h2>
          <span className="text-xs text-gray-500">點擊卡片加入趨勢圖</span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {criticalCount > 0 && (
            <span className="bg-red-600 px-2.5 py-0.5 rounded-full font-bold animate-pulse">
              {criticalCount} 癱瘓
            </span>
          )}
          {congestedCount > 0 && (
            <span className="bg-yellow-500 text-black px-2.5 py-0.5 rounded-full font-bold">
              {congestedCount} 壅擠
            </span>
          )}
          <span className="text-gray-500">{timestamp}</span>
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
              className={`rounded-lg border p-3 cursor-pointer transition hover:scale-[1.02] active:scale-95 ${cardStyle(seg.level, inChart)}`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-gray-200 truncate">{seg.road_name}</span>
                <div className="flex items-center gap-1">
                  {inChart && <Check className="w-3 h-3 text-blue-400" />}
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${status.cls}`}>
                    {status.text}
                  </span>
                </div>
              </div>

              <div className="w-full bg-gray-700/60 rounded-full h-2 mb-2">
                <div className={`h-2 rounded-full transition-all ${barColor(seg.level)}`} style={{ width: `${Math.min(pct, 100)}%` }} />
              </div>

              <div className="flex items-center justify-between text-[11px]">
                <span className={`font-bold ${seg.level === "A" ? "text-red-400" : seg.level === "B" ? "text-yellow-400" : "text-green-400"}`}>{pct}%</span>
                <span className="text-gray-500">{seg.avg_speed} km/h</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
