import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Crosshair } from "lucide-react";
import ThreatGrid from "./ThreatGrid";
import TrendChart from "./TrendChart";
import AlertTicker from "./AlertTicker";
import CityMap3D from "./CityMap3D";
import StreetCam from "./StreetCam";
import { cn } from "../lib/utils";

const LEVEL_ORDER = { A: 0, B: 1, Normal: 2 };

// 輪詢節奏：後端模擬時鐘會回報下一次時間變動的秒數，前端照它排程。
const MIN_POLL_MS = 1000;
const MAX_POLL_MS = 30000;
const IDLE_POLL_MS = 10000;

export default function DashboardTab() {
  const [segments, setSegments] = useState([]);
  const [stations, setStations] = useState([]);
  const [ts, setTs] = useState("");
  const [showAlert, setShowAlert] = useState(false);
  const [alertShownOnce, setAlertShownOnce] = useState(false);
  const [chartSegments, setChartSegments] = useState([]);
  const [autoAdvisories, setAutoAdvisories] = useState([]);
  const [pinnedSegmentId, setPinnedSegmentId] = useState(null);
  const alertShownRef = useRef(false);

  useEffect(() => {
    let timer;
    let cancelled = false;

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
        setStations(data.stations || []);
        setTs(data.timestamp || "");
        setAutoAdvisories(data.auto_advisories || []);

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

  // 街景鎖定路段：先看使用者釘選，否則取威脅等級最高、同級取飽和度最高者
  const camSegment = useMemo(() => {
    const pinned = segments.find((s) => s.segment_id === pinnedSegmentId);
    if (pinned) return pinned;
    return (
      [...segments].sort(
        (a, b) =>
          (LEVEL_ORDER[a.level] ?? 3) - (LEVEL_ORDER[b.level] ?? 3) ||
          b.saturation_score - a.saturation_score,
      )[0] || null
    );
  }, [segments, pinnedSegmentId]);

  // 選單只列異常路段，正常時段不佔畫面
  const abnormalSegments = useMemo(
    () =>
      segments
        .filter((s) => s.level === "A" || s.level === "B")
        .sort(
          (a, b) =>
            (LEVEL_ORDER[a.level] ?? 3) - (LEVEL_ORDER[b.level] ?? 3) ||
            b.saturation_score - a.saturation_score,
        ),
    [segments],
  );

  return (
    <div className="space-y-4">
      {/* 3D 城市地圖：道路飽和度即時漸變，點擊路段加入趨勢圖 */}
      <CityMap3D
        segments={segments}
        stations={stations}
        selectedSegmentIds={chartSegments.map((s) => s.segment_id)}
        onSegmentClick={handleAddToChart}
        className="h-[520px]"
      />

      <ThreatGrid
        segments={segments}
        timestamp={ts}
        onAddToChart={handleAddToChart}
        chartSegmentIds={chartSegments.map((s) => s.segment_id)}
      />

      <TrendChart
        selectedSegments={chartSegments}
        onRemove={handleRemoveFromChart}
        simTime={ts}
      />

      {/* 底部：左為預警快訊與自動路徑引導，右為該路段即時街景 */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
        <AlertTicker segments={segments} autoAdvisories={autoAdvisories} />

        <div className="space-y-2">
          {/* 路段切換：預設追蹤最嚴重路段，可手動釘選 */}
          {abnormalSegments.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                onClick={() => setPinnedSegmentId(null)}
                title="自動追蹤最嚴重路段"
                className={cn(
                  "flex items-center gap-1 px-2.5 py-1 rounded-sm text-xs border transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                  pinnedSegmentId === null
                    ? "bg-[var(--accent)] text-[var(--accent-foreground)] border-[var(--primary)] font-medium"
                    : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)] hover:bg-[var(--accent)]",
                )}
              >
                <Crosshair className="w-3 h-3" />
                自動追蹤
              </button>
              {abnormalSegments.map((seg) => (
                <button
                  key={seg.segment_id}
                  onClick={() => setPinnedSegmentId(seg.segment_id)}
                  title={`飽和度 ${Math.round(seg.saturation_score * 100)}%`}
                  className={cn(
                    "px-2.5 py-1 rounded-sm text-xs whitespace-nowrap border transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                    camSegment?.segment_id === seg.segment_id
                      ? "bg-[var(--status-error)]/10 text-[var(--status-error)] border-[var(--status-error)]/40 font-medium"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)] hover:bg-[var(--accent)]",
                  )}
                >
                  {seg.road_name}
                  <span className="ml-1 text-[var(--muted-foreground)]">{seg.level}</span>
                </button>
              ))}
            </div>
          )}

          <StreetCam
            segmentId={camSegment?.segment_id}
            label={
              camSegment
                ? `${camSegment.road_name}　飽和度 ${Math.round(camSegment.saturation_score * 100)}%`
                : ""
            }
            title="路段即時街景"
            emptyHint="等待路網資料"
          />
        </div>
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
