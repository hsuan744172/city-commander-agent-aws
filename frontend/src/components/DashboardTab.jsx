import { useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import ThreatGrid from "./ThreatGrid";
import TrendChart from "./TrendChart";
import AlertTicker from "./AlertTicker";
import CityMap3D from "./CityMap3D";

// 輪詢節奏：後端模擬時鐘會回報下一次時間變動的秒數，前端照它排程。
const MIN_POLL_MS = 1000;      // 避免時鐘 interval 設太小時打爆後端
const MAX_POLL_MS = 30000;
const IDLE_POLL_MS = 10000;    // fixed / latest 模式：時間不會動，慢慢輪即可

export default function DashboardTab() {
  const [segments, setSegments] = useState([]);
  const [ts, setTs] = useState("");
  const [showAlert, setShowAlert] = useState(false);
  const [alertShownOnce, setAlertShownOnce] = useState(false);
  const [chartSegments, setChartSegments] = useState([]);
  const [autoAdvisories, setAutoAdvisories] = useState([]);
  const alertShownRef = useRef(false);

  useEffect(() => {
    let timer;
    let cancelled = false;

    // 跟著後端時鐘走：時鐘 interval 或模式改變時，前端不需要跟著改設定。
    // 連續模式 (smooth/auto) 回報固定輪詢節奏；playback 則對齊下次跳格的時間點。
    const scheduleNext = (clock) => {
      const hint = clock?.suggested_poll_seconds ?? clock?.next_change_in_seconds;
      const delay =
        hint == null
          ? IDLE_POLL_MS
          : Math.min(Math.max(hint * 1000 + 250, MIN_POLL_MS), MAX_POLL_MS);
      timer = setTimeout(load, delay);
    };

    const load = async () => {
      let clock = null;
      try {
        const res = await fetch("/api/status");
        const data = await res.json();
        if (cancelled) return;

        clock = data.clock;
        setSegments(data.segments || []);
        setTs(data.timestamp || "");
        setAutoAdvisories(data.auto_advisories || []);

        // 首次載入自動彈一次警報
        if (!alertShownRef.current) {
          const hasCritical = (data.segments || []).some((s) => s.level === "A" || s.level === "B");
          if (hasCritical) {
            alertShownRef.current = true;
            setShowAlert(true);
            setAlertShownOnce(true);
          }
        }
      } catch {}
      if (!cancelled) scheduleNext(clock);
    };

    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  // 點擊卡片：toggle 加入/移除折線圖
  const handleAddToChart = (segment) => {
    setChartSegments((prev) => {
      if (prev.find((s) => s.segment_id === segment.segment_id)) {
        return prev.filter((s) => s.segment_id !== segment.segment_id);
      }
      return [...prev, segment];
    });
  };

  const handleRemoveFromChart = (segmentId) => {
    setChartSegments((prev) => prev.filter((s) => s.segment_id !== segmentId));
  };

  return (
    <div className="space-y-4">
      {/* 3D 城市地圖：道路飽和度即時漸變 */}
      <CityMap3D segments={segments} className="h-[520px]" />

      {/* 頂部：威脅網格 (可拖拉進折線圖) */}
      <ThreatGrid
        segments={segments}
        timestamp={ts}
        onAddToChart={handleAddToChart}
        chartSegmentIds={chartSegments.map((s) => s.segment_id)}
      />

      {/* 中段：折線圖 (預設空，由上方拖入)；simTime 變動時重抓，讓曲線隨時鐘成長 */}
      <TrendChart
        selectedSegments={chartSegments}
        onRemove={handleRemoveFromChart}
        simTime={ts}
      />

      {/* 底部：預警快訊 + 自動路徑引導 */}
      <AlertTicker segments={segments} autoAdvisories={autoAdvisories} />

      {/* 警報按鈕 (關閉後可重新打開) */}
      {!showAlert && alertShownOnce && (
        <button
          onClick={() => setShowAlert(true)}
          className="fixed bottom-6 right-6 flex items-center gap-2 px-4 py-2.5 bg-red-600 hover:bg-red-500 rounded-full shadow-lg text-sm font-medium transition z-40"
        >
          <AlertTriangle className="w-4 h-4" />
          查看預警
        </button>
      )}

      {/* Alert Modal (只自動彈一次，之後靠按鈕開) */}
      {showAlert && (
        <AlertModal segments={segments} onClose={() => setShowAlert(false)} />
      )}
    </div>
  );
}

function AlertModal({ segments, onClose }) {
  const critical = segments.filter((s) => s.level === "A");
  const congested = segments.filter((s) => s.level === "B");

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white border border-red-300 rounded-2xl p-6 max-w-lg w-full shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="w-6 h-6 text-red-400" />
          <h3 className="text-lg font-bold text-red-700">路網異常預警摘要</h3>
        </div>

        {critical.length > 0 && (
          <div className="mb-3">
            <div className="text-xs font-semibold text-red-400 mb-1">A 級癱瘓（飽和度 ≥ 95%）</div>
            <div className="space-y-1">
              {critical.map((s) => (
                <div key={s.segment_id} className="text-sm text-red-700 bg-red-900/30 px-3 py-1.5 rounded">
                  {s.road_name} — {Math.round(s.saturation_score * 100)}%，時速 {s.avg_speed} km/h
                </div>
              ))}
            </div>
          </div>
        )}

        {congested.length > 0 && (
          <div className="mb-3">
            <div className="text-xs font-semibold text-yellow-400 mb-1">B 級壅擠（飽和度 ≥ 85%）</div>
            <div className="space-y-1">
              {congested.map((s) => (
                <div key={s.segment_id} className="text-sm text-yellow-700 bg-yellow-900/20 px-3 py-1.5 rounded">
                  {s.road_name} — {Math.round(s.saturation_score * 100)}%，時速 {s.avg_speed} km/h
                </div>
              ))}
            </div>
          </div>
        )}

        <button onClick={onClose} className="mt-4 w-full py-2.5 bg-gray-200 hover:bg-gray-300 rounded-lg text-sm font-medium transition">
          關閉
        </button>
      </div>
    </div>
  );
}
