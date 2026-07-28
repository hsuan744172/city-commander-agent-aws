import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import ThreatGrid from "./ThreatGrid";
import TrendChart from "./TrendChart";
import AlertTicker from "./AlertTicker";

export default function DashboardTab() {
  const [segments, setSegments] = useState([]);
  const [ts, setTs] = useState("");
  const [showAlert, setShowAlert] = useState(false);
  const [alertShownOnce, setAlertShownOnce] = useState(false);
  const [chartSegments, setChartSegments] = useState([]);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch("/api/status");
        const data = await res.json();
        setSegments(data.segments || []);
        setTs(data.timestamp || "");

        // 首次載入自動彈一次警報
        if (!alertShownOnce) {
          const hasCritical = (data.segments || []).some((s) => s.level === "A" || s.level === "B");
          if (hasCritical) {
            setShowAlert(true);
            setAlertShownOnce(true);
          }
        }
      } catch {}
    };
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [alertShownOnce]);

  // 拖拉加入折線圖
  const handleAddToChart = (segment) => {
    setChartSegments((prev) => {
      if (prev.find((s) => s.segment_id === segment.segment_id)) return prev;
      return [...prev, segment];
    });
  };

  const handleRemoveFromChart = (segmentId) => {
    setChartSegments((prev) => prev.filter((s) => s.segment_id !== segmentId));
  };

  return (
    <div className="space-y-4">
      {/* 頂部：威脅網格 (可拖拉進折線圖) */}
      <ThreatGrid
        segments={segments}
        timestamp={ts}
        onAddToChart={handleAddToChart}
        chartSegmentIds={chartSegments.map((s) => s.segment_id)}
      />

      {/* 中段：折線圖 (預設空，由上方拖入) */}
      <TrendChart
        selectedSegments={chartSegments}
        onRemove={handleRemoveFromChart}
      />

      {/* 底部：預警快訊 */}
      <AlertTicker segments={segments} />

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
      <div className="bg-gray-900 border border-red-600/60 rounded-2xl p-6 max-w-lg w-full shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="w-6 h-6 text-red-400" />
          <h3 className="text-lg font-bold text-red-200">路網異常預警摘要</h3>
        </div>

        {critical.length > 0 && (
          <div className="mb-3">
            <div className="text-xs font-semibold text-red-400 mb-1">A 級癱瘓（飽和度 ≥ 95%）</div>
            <div className="space-y-1">
              {critical.map((s) => (
                <div key={s.segment_id} className="text-sm text-red-200 bg-red-900/30 px-3 py-1.5 rounded">
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
                <div key={s.segment_id} className="text-sm text-yellow-200 bg-yellow-900/20 px-3 py-1.5 rounded">
                  {s.road_name} — {Math.round(s.saturation_score * 100)}%，時速 {s.avg_speed} km/h
                </div>
              ))}
            </div>
          </div>
        )}

        <button onClick={onClose} className="mt-4 w-full py-2.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition">
          關閉
        </button>
      </div>
    </div>
  );
}
