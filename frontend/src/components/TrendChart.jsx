import { useEffect, useState } from "react";
import { TrendingUp, X } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from "recharts";

// 線條顏色依威脅等級：A 紅、B 橘、其餘藍
function lineColor(level) {
  if (level === "A") return "#EF4444";
  if (level === "B") return "#F59E0B";
  return "#3B82F6";
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-3 shadow-sm min-w-[180px]">
      <div className="text-xs text-[var(--muted-foreground)] mb-2 font-medium">{label}</div>
      <div className="space-y-1">
        {payload
          .filter((p) => p.value != null)
          .sort((a, b) => b.value - a.value)
          .map((p, i) => {
            const pct = Math.round(p.value * 100);
            const icon = pct >= 95 ? "🔴" : pct >= 85 ? "🟡" : "🟢";
            return (
              <div key={i} className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                  <span className="text-xs text-[var(--foreground)]">{p.name}</span>
                </div>
                <span className="text-xs font-bold">{icon} {pct}%</span>
              </div>
            );
          })}
      </div>
    </div>
  );
}

/**
 * 飽和度趨勢圖（單選一條路段）
 * selectedSegment：由儀表板點擊路段或事件小卡帶入的路段
 * onClear：有提供時顯示取消選取按鈕
 */
export default function TrendChart({ selectedSegment, onClear, simTime }) {
  const [allData, setAllData] = useState([]);
  const chartHeight = 280;

  // 後端只回傳「截至當下模擬時間」的資料，因此時間一推進就要重抓
  useEffect(() => {
    let cancelled = false;
    fetch("/api/trend")
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setAllData(d.data || []);
      })
      .catch(() => {
        if (!cancelled) setAllData([]);
      });
    return () => {
      cancelled = true;
    };
  }, [simTime]);

  const hasSelection = Boolean(selectedSegment?.segment_id);
  const color = lineColor(selectedSegment?.level);

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-[var(--primary)]" />
          <h2 className="text-sm font-semibold">飽和度趨勢圖</h2>
        </div>
        {hasSelection ? (
          <span className="flex items-center gap-1 px-2.5 py-1 bg-[var(--secondary)] border border-[var(--border)] rounded-full text-xs">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
            {selectedSegment.road_name}
            {onClear && (
              <button
                onClick={() => onClear()}
                title="取消選取"
                className="ml-0.5 hover:text-[var(--status-error)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </span>
        ) : (
          <span className="text-xs text-[var(--muted-foreground)]">尚未選定路段</span>
        )}
      </div>

      {/* Chart or Empty State */}
      {!hasSelection ? (
        <div className="h-64 flex flex-col items-center justify-center text-[var(--muted-foreground)] border-2 border-dashed border-[var(--border)] rounded-lg">
          <TrendingUp className="w-10 h-10 mb-2 opacity-30" />
          <span className="text-sm">於儀表板點擊路段或事件小卡，即可顯示該路段飽和度趨勢</span>
        </div>
      ) : allData.length === 0 ? (
        <div
          className="flex items-center justify-center text-[var(--muted-foreground)] text-sm"
          style={{ height: chartHeight }}
        >
          載入中...
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={chartHeight}>
          <LineChart data={allData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="time" stroke="var(--muted-foreground)" fontSize={11} />
            <YAxis stroke="var(--muted-foreground)" fontSize={11} domain={[0, 1.05]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
            <ReferenceLine y={0.95} stroke="var(--status-error)" strokeDasharray="4 4" strokeOpacity={0.5} />
            <ReferenceLine y={0.85} stroke="var(--status-warning)" strokeDasharray="4 4" strokeOpacity={0.5} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12 }} iconType="circle" iconSize={8} />
            <Line
              type="monotone"
              dataKey={selectedSegment.segment_id}
              name={selectedSegment.road_name}
              stroke={color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2 }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
