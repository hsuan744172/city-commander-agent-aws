import { TrendingUp } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

// 線條顏色依 SOP 第 1 條分級：A 紅、B 橘、正常藍
function lineColor(level) {
  if (level === "A") return "#EF4444";
  if (level === "B") return "#F59E0B";
  return "#3B82F6";
}

// 列印時 SVG 拿不到頁面的 CSS 變數，格線與座標軸必須給實色，
// 否則匯出的 PDF 只會剩下一條線、沒有座標軸與門檻線。
const PRINT_PALETTE = {
  grid: "#C9D6D2",
  axis: "#4A5A55",
  levelA: "#B91C1C",
  levelB: "#B45309",
};

const SCREEN_PALETTE = {
  grid: "var(--border)",
  axis: "var(--muted-foreground)",
  levelA: "var(--status-error)",
  levelB: "var(--status-warning)",
};

function CustomTooltip({ active, payload, label, levelA = 0.95, levelB = 0.85 }) {
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
            return (
              <div key={i} className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                  <span className="text-xs text-[var(--foreground)]">{p.name}</span>
                </div>
                <span
                  className="text-xs font-bold"
                  style={{
                    color:
                      p.value >= levelA
                        ? "var(--status-error)"
                        : p.value >= levelB
                          ? "var(--status-warning)"
                          : "var(--status-success)",
                  }}
                >
                  {pct}%
                </span>
              </div>
            );
          })}
      </div>
    </div>
  );
}

/**
 * 飽和度趨勢圖（單一路段）
 *
 * data 由呼叫端傳入（useTrendSeries），螢幕與匯出報告共用同一份資料。
 * 路段名稱由監控頁頁首統一標示，這裡不重複掛標籤，也不需要圖例（只有一條線）。
 *
 * variant="print" 時改用固定尺寸與實色配色，並關閉動畫：
 * 報告節點在螢幕上是隱藏的，ResponsiveContainer 量到的寬度會是 0，
 * 進場動畫也不會播完，兩者都會讓列印出來的圖是空白。
 */
export default function TrendChart({
  selectedSegment,
  data = [],
  loading = false,
  thresholds,
  variant = "screen",
}) {
  const isPrint = variant === "print";
  const palette = isPrint ? PRINT_PALETTE : SCREEN_PALETTE;
  const chartHeight = isPrint ? 240 : 280;
  // 門檻由後端 /api/status 提供，前端不再自己寫死 0.95 / 0.85
  const levelA = thresholds?.level_a ?? 0.95;
  const levelB = thresholds?.level_b ?? 0.85;

  const hasSelection = Boolean(selectedSegment?.segment_id);
  const color = lineColor(selectedSegment?.level);

  const chart = (
    <LineChart
      data={data}
      width={isPrint ? 660 : undefined}
      height={isPrint ? chartHeight : undefined}
      margin={{ top: 8, right: 20, left: 0, bottom: 5 }}
    >
      <CartesianGrid strokeDasharray="3 3" stroke={palette.grid} />
      <XAxis
        dataKey="time"
        stroke={palette.axis}
        fontSize={11}
        tickFormatter={(value) => String(value).slice(-5)}
      />
      <YAxis
        stroke={palette.axis}
        fontSize={11}
        domain={[0, 1.05]}
        tickFormatter={(v) => `${Math.round(v * 100)}%`}
      />
      <ReferenceLine
        y={levelA}
        stroke={palette.levelA}
        strokeDasharray="4 4"
        strokeOpacity={isPrint ? 0.8 : 0.5}
        label={{
          value: `A 級 ${Math.round(levelA * 100)}%`,
          position: "insideTopRight",
          fontSize: 10,
          fill: palette.levelA,
        }}
      />
      <ReferenceLine
        y={levelB}
        stroke={palette.levelB}
        strokeDasharray="4 4"
        strokeOpacity={isPrint ? 0.8 : 0.5}
        label={{
          value: `B 級 ${Math.round(levelB * 100)}%`,
          position: "insideTopRight",
          fontSize: 10,
          fill: palette.levelB,
        }}
      />
      {!isPrint && <Tooltip content={<CustomTooltip levelA={levelA} levelB={levelB} />} />}
      <Line
        type="monotone"
        dataKey={selectedSegment?.segment_id}
        name={selectedSegment?.road_name}
        stroke={color}
        strokeWidth={2}
        dot={isPrint ? { r: 2 } : false}
        activeDot={isPrint ? false : { r: 4, strokeWidth: 2 }}
        isAnimationActive={!isPrint}
        connectNulls
      />
    </LineChart>
  );

  if (isPrint) {
    if (!hasSelection || data.length === 0) {
      return <p className="report-note">趨勢資料不足，無法繪製曲線。</p>;
    }
    return chart;
  }

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-[var(--primary)]" />
          <h2 className="text-sm font-semibold">飽和度趨勢圖</h2>
        </div>
        <span className="text-xs text-[var(--muted-foreground)]">
          虛線為 SOP 第 1 條分級門檻
        </span>
      </div>

      {!hasSelection ? (
        <div className="h-64 flex flex-col items-center justify-center text-[var(--muted-foreground)] border-2 border-dashed border-[var(--border)] rounded-lg">
          <TrendingUp className="w-10 h-10 mb-2 opacity-30" />
          <span className="text-sm">等待路網資料</span>
        </div>
      ) : loading || data.length === 0 ? (
        <div
          className="flex items-center justify-center text-[var(--muted-foreground)] text-sm"
          style={{ height: chartHeight }}
        >
          {loading ? "載入中…" : "此時間點尚無趨勢資料"}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={chartHeight}>
          {chart}
        </ResponsiveContainer>
      )}
    </div>
  );
}
