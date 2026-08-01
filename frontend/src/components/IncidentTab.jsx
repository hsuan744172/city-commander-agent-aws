import { useMemo } from "react";
import { ArrowLeft, Crosshair, Activity } from "lucide-react";
import AutoAdvisoryPanel from "./AutoAdvisoryPanel";
import StreetCam from "./StreetCam";
import TrendChart from "./TrendChart";
import { cn } from "../lib/utils";

const LEVEL_ORDER = { A: 0, B: 1, Normal: 2 };

function levelBadge(level) {
  if (level === "A") {
    return {
      text: "A 級癱瘓",
      cls: "bg-[var(--status-error)] text-[var(--primary-foreground)]",
    };
  }
  if (level === "B") {
    return {
      text: "B 級壅擠",
      cls: "bg-[var(--status-warning)] text-[var(--primary-foreground)]",
    };
  }
  return {
    text: "正常",
    cls: "bg-[var(--status-success)] text-[var(--primary-foreground)]",
  };
}

/**
 * 路網即時監控
 *
 * 只負責即時路況、趨勢、自動應變與街景。事件注入產出的建議書留在注入頁原地處置，
 * 避免監控頁同時承擔歷史報告與跨頁狀態同步。
 */
export default function IncidentTab({
  network,
  selectedSegmentId = null,
  onSelectSegment,
  onBackToDashboard,
}) {
  const { segments, timestamp, autoAdvisories, monitoredAlerts, thresholds } = network;

  const orderedSegments = useMemo(
    () =>
      [...segments].sort(
        (a, b) =>
          (LEVEL_ORDER[a.level] ?? 3) - (LEVEL_ORDER[b.level] ?? 3) ||
          b.saturation_score - a.saturation_score,
      ),
    [segments],
  );

  const selectedSegment = useMemo(
    () => segments.find((segment) => segment.segment_id === selectedSegmentId) || null,
    [segments, selectedSegmentId],
  );
  const detailSegment = selectedSegment || orderedSegments[0] || null;
  const badge = levelBadge(detailSegment?.level);
  const focusedAdvisories = selectedSegmentId
    ? autoAdvisories.filter((advisory) => advisory.segment_id === selectedSegmentId)
    : autoAdvisories;

  return (
    <div className="space-y-4">
      <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4 shadow-sm">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <Activity className="w-5 h-5 text-[var(--primary)]" />
              <h2 className="text-xl font-bold">路網即時監控</h2>
              {detailSegment && (
                <span className={cn("text-xs px-2 py-0.5 rounded-sm font-bold", badge.cls)}>
                  {badge.text}
                </span>
              )}
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              追蹤異常路段、自動應變、飽和度趨勢與即時街景；點選路段即可鎖定觀測。
            </p>
            {detailSegment && (
              <div className="flex items-center gap-3 text-xs text-[var(--muted-foreground)] flex-wrap">
                <span className="font-medium text-[var(--foreground)]">{detailSegment.road_name}</span>
                <span>飽和度 {Math.round(detailSegment.saturation_score * 100)}%</span>
                <span>平均時速 {detailSegment.avg_speed} 公里</span>
                <span>車流量 {detailSegment.vehicle_count} 輛</span>
                <span>{detailSegment.lane_status}</span>
                {timestamp && <span>資料時間 {timestamp}</span>}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={onBackToDashboard}
            className="flex items-center gap-1 px-2.5 py-1 rounded-sm text-xs border border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            <ArrowLeft className="w-3 h-3" />
            返回儀表板
          </button>
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap" aria-label="監控路段切換">
        <button
          type="button"
          onClick={() => onSelectSegment?.(null)}
          title="自動追蹤最嚴重路段"
          className={cn(
            "flex items-center gap-1 px-2.5 py-1 rounded-sm text-xs border transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
            selectedSegmentId === null
              ? "bg-[var(--accent)] text-[var(--accent-foreground)] border-[var(--primary)] font-medium"
              : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)] hover:bg-[var(--accent)]",
          )}
        >
          <Crosshair className="w-3 h-3" />
          自動追蹤
        </button>
        {orderedSegments.map((segment) => (
          <button
            key={segment.segment_id}
            type="button"
            onClick={() => onSelectSegment?.(segment.segment_id)}
            title={`飽和度 ${Math.round(segment.saturation_score * 100)}%`}
            className={cn(
              "px-2.5 py-1 rounded-sm text-xs whitespace-nowrap border transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
              detailSegment?.segment_id === segment.segment_id && selectedSegmentId !== null
                ? "bg-[var(--primary)]/15 text-[var(--foreground)] border-[var(--primary)] font-medium"
                : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)] hover:bg-[var(--accent)]",
            )}
          >
            {segment.road_name}
            <span className="ml-1 text-[var(--muted-foreground)]">{segment.level}</span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
        <div className="space-y-4">
          <AutoAdvisoryPanel
            advisories={focusedAdvisories}
            monitoredAlerts={selectedSegmentId ? [] : monitoredAlerts}
          />
          <TrendChart
            selectedSegment={detailSegment}
            simTime={timestamp}
            thresholds={thresholds}
          />
        </div>

        <StreetCam
          segmentId={detailSegment?.segment_id}
          label={
            detailSegment
              ? `${detailSegment.road_name}　飽和度 ${Math.round(detailSegment.saturation_score * 100)}%`
              : ""
          }
          title="路段即時街景"
          emptyHint="等待路網資料"
        />
      </div>
    </div>
  );
}
