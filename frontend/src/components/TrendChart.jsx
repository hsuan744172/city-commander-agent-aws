import { useEffect, useState } from "react";
import { TrendingUp, X } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from "recharts";

const COLORS = ["#EF4444", "#F59E0B", "#3B82F6", "#10B981", "#8B5CF6", "#EC4899", "#06B6D4", "#F97316"];

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 shadow-xl min-w-[180px]">
      <div className="text-xs text-gray-400 mb-2 font-medium">{label}</div>
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
                  <span className="text-xs text-gray-300">{p.name}</span>
                </div>
                <span className="text-xs font-bold text-gray-100">{icon} {pct}%</span>
              </div>
            );
          })}
      </div>
    </div>
  );
}

export default function TrendChart({ selectedSegments, onRemove }) {
  const [allData, setAllData] = useState([]);

  useEffect(() => {
    fetch("/api/trend")
      .then((r) => r.json())
      .then((d) => setAllData(d.data || []))
      .catch(() => setAllData([]));
  }, []);

  const hasSelection = selectedSegments?.length > 0;

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-blue-400" />
          <h2 className="text-sm font-semibold text-gray-200">飽和度趨勢圖</h2>
        </div>
        {!hasSelection && (
          <span className="text-xs text-gray-500">← 點擊上方路段卡片加入監測</span>
        )}
      </div>

      {/* Selected Segment Tags */}
      {hasSelection && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {selectedSegments.map((seg, idx) => (
            <span
              key={seg.segment_id}
              className="flex items-center gap-1 px-2.5 py-1 bg-gray-800 border border-gray-700 rounded-full text-xs text-gray-300"
            >
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }} />
              {seg.road_name}
              <button onClick={() => onRemove(seg.segment_id)} className="ml-0.5 hover:text-red-400 transition">
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Chart or Empty State */}
      {!hasSelection ? (
        <div className="h-64 flex flex-col items-center justify-center text-gray-500 border-2 border-dashed border-gray-800 rounded-xl">
          <TrendingUp className="w-10 h-10 mb-2 opacity-30" />
          <span className="text-sm">點擊上方路段卡片加入趨勢監測</span>
        </div>
      ) : allData.length === 0 ? (
        <div className="h-64 flex items-center justify-center text-gray-500 text-sm">
          載入中...
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={allData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
            <XAxis dataKey="time" stroke="#6B7280" fontSize={11} />
            <YAxis stroke="#6B7280" fontSize={11} domain={[0, 1.05]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
            <ReferenceLine y={0.95} stroke="#EF4444" strokeDasharray="4 4" strokeOpacity={0.5} />
            <ReferenceLine y={0.85} stroke="#F59E0B" strokeDasharray="4 4" strokeOpacity={0.5} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12 }} iconType="circle" iconSize={8} />
            {selectedSegments.map((seg, idx) => (
              <Line
                key={seg.segment_id}
                type="monotone"
                dataKey={seg.segment_id}
                name={seg.road_name}
                stroke={COLORS[idx % COLORS.length]}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
