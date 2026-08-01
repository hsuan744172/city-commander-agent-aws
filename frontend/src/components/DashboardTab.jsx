import { useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import ThreatGrid from "./ThreatGrid";
import CityMap3D from "./CityMap3D";
import useNetworkStatus from "../lib/useNetworkStatus";

/**
 * 即時儀表板：只保留路網地圖與路段事件小卡。
 * 點擊地圖路段或小卡 → 跳往「事件處置與建議書」並聚焦該路段。
 */
export default function DashboardTab({ onInspectSegment }) {
  const { segments, stations, timestamp } = useNetworkStatus();
  const [showAlert, setShowAlert] = useState(false);
  const [alertShownOnce, setAlertShownOnce] = useState(false);
  const alertShownRef = useRef(false);

  // 首次偵測到 A/B 級異常時自動彈出預警摘要
  useEffect(() => {
    if (alertShownRef.current) return;
    if (!segments.some((s) => s.level === "A" || s.level === "B")) return;
    alertShownRef.current = true;
    setShowAlert(true);
    setAlertShownOnce(true);
  }, [segments]);

  return (
    <div className="space-y-4">
      {/* 左為 3D 城市地圖，右為路段事件小卡；兩者點擊皆跳往建議書頁 */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
        <CityMap3D
          segments={segments}
          stations={stations}
          onSegmentClick={onInspectSegment}
          className="xl:col-span-3 h-[620px]"
        />

        <ThreatGrid
          segments={segments}
          timestamp={timestamp}
          onSelect={onInspectSegment}
          className="xl:col-span-1 h-[620px]"
        />
      </div>

      {!showAlert && alertShownOnce && (
        <button
          onClick={() => setShowAlert(true)}
          className="fixed bottom-6 right-6 flex items-center gap-2 px-4 py-2.5 bg-[var(--status-error)] hover:opacity-90 text-[var(--primary-foreground)] rounded-full shadow-sm text-sm font-medium transition z-40"
        >
          <AlertTriangle className="w-4 h-4" />
          查看預警
        </button>
      )}

      {showAlert && <AlertModal segments={segments} onClose={() => setShowAlert(false)} />}
    </div>
  );
}

function AlertModal({ segments, onClose }) {
  const critical = segments.filter((s) => s.level === "A");
  const congested = segments.filter((s) => s.level === "B");

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-xl p-6 max-w-lg w-full shadow-sm" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="w-6 h-6 text-[var(--status-error)]" />
          <h3 className="text-lg font-semibold text-[var(--status-error)]">路網異常預警摘要</h3>
        </div>

        {critical.length > 0 && (
          <div className="mb-3">
            <div className="text-xs font-semibold text-[var(--status-error)] mb-1">A 級癱瘓（飽和度 ≥ 95%）</div>
            <div className="space-y-1">
              {critical.map((s) => (
                <div key={s.segment_id} className="text-sm text-[var(--foreground)] bg-[var(--status-error)]/10 px-3 py-1.5 rounded-md">
                  {s.road_name} — {Math.round(s.saturation_score * 100)}%，時速 {s.avg_speed} km/h
                </div>
              ))}
            </div>
          </div>
        )}

        {congested.length > 0 && (
          <div className="mb-3">
            <div className="text-xs font-semibold text-[var(--status-warning)] mb-1">B 級壅擠（飽和度 ≥ 85%）</div>
            <div className="space-y-1">
              {congested.map((s) => (
                <div key={s.segment_id} className="text-sm text-[var(--foreground)] bg-[var(--status-warning)]/10 px-3 py-1.5 rounded-md">
                  {s.road_name} — {Math.round(s.saturation_score * 100)}%，時速 {s.avg_speed} km/h
                </div>
              ))}
            </div>
          </div>
        )}

        <button onClick={onClose} className="mt-4 w-full py-2.5 bg-[var(--secondary)] hover:bg-[var(--accent)] text-[var(--secondary-foreground)] rounded-md text-sm font-medium transition">
          關閉
        </button>
      </div>
    </div>
  );
}
