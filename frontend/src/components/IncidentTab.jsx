import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Crosshair, LayoutGrid, Siren } from "lucide-react";
import IncidentMap from "./IncidentMap";
import AdvisoryCard from "./AdvisoryCard";
import StreetCam from "./StreetCam";
import AlertTicker from "./AlertTicker";
import TrendChart from "./TrendChart";
import useNetworkStatus from "../lib/useNetworkStatus";
import { fetchRecentInjections } from "../lib/incidentInjection";
import { cn } from "../lib/utils";

const LEVEL_ORDER = { A: 0, B: 1, Normal: 2 };

function levelBadge(level) {
  if (level === "A") return { text: "A 級癱瘓", cls: "bg-[var(--status-error)] text-[var(--primary-foreground)]" };
  if (level === "B") return { text: "B 級壅擠", cls: "bg-[var(--status-warning)] text-[var(--primary-foreground)]" };
  return { text: "正常", cls: "bg-[var(--status-success)] text-[var(--primary-foreground)]" };
}

/**
 * 事件處置與建議書
 * report：本次事件注入產出的建議書（來自事件注入頁）
 * focusSegmentId：由儀表板點擊路段或事件小卡帶入，聚焦顯示該路段的處置資訊
 */
export default function IncidentTab({
  report: injectedReport = null,
  focusSegmentId = null,
  onClearFocus,
  onBackToDashboard,
  onOpenInjection,
}) {
  // 建議書來源：本次注入的結果優先；重新整理後改由最後一筆注入紀錄補回，
  // 值班席位不必重新注入就能看到現行處置。
  const [latestReport, setLatestReport] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [pinnedSegmentId, setPinnedSegmentId] = useState(null);
  const { segments, timestamp, autoAdvisories } = useNetworkStatus();

  useEffect(() => {
    if (injectedReport) return undefined;
    let cancelled = false;
    fetchRecentInjections({ limit: 1, includeReport: true })
      .then((body) => {
        if (!cancelled) setLatestReport(body.injections?.[0]?.report || null);
      })
      .catch(() => {
        // 沒有注入紀錄時維持空白狀態即可
      });
    return () => {
      cancelled = true;
    };
  }, [injectedReport]);

  const report = injectedReport || latestReport;
  const advisories = report?.advisories || [];
  const selectedAdvisory = advisories[selectedIdx] || null;

  // 街景與趨勢鎖定路段：先看儀表板帶入的聚焦路段，再看手動釘選，
  // 都沒有時取威脅等級最高、同級取飽和度最高者
  const focusSegment = useMemo(
    () => segments.find((s) => s.segment_id === focusSegmentId) || null,
    [segments, focusSegmentId],
  );

  const trackedSegment = useMemo(() => {
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

  const focusMode = Boolean(focusSegmentId);
  const detailSegment = focusSegment || trackedSegment;

  // 聚焦模式只呈現該路段的預警與自動路徑引導
  const tickerSegments = focusMode && focusSegment ? [focusSegment] : segments;
  const tickerAdvisories = focusMode
    ? autoAdvisories.filter((a) => a.segment_id === focusSegmentId)
    : autoAdvisories;

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

  // 點路段切換鈕代表改為手動追蹤，離開儀表板帶入的聚焦狀態
  const pinSegment = (segmentId) => {
    setPinnedSegmentId(segmentId);
    if (focusMode) onClearFocus?.();
  };

  const badge = levelBadge(detailSegment?.level);

  return (
    <div className="space-y-4">
      {/* 聚焦路段標題列：由儀表板點擊帶入 */}
      {focusMode && (
        <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold">
                  {focusSegment?.road_name || focusSegmentId}
                </h2>
                <span className={cn("text-xs px-2 py-0.5 rounded-sm font-bold", badge.cls)}>
                  {badge.text}
                </span>
              </div>

              {focusSegment ? (
                <div className="flex items-center gap-3 text-xs text-[var(--muted-foreground)] flex-wrap">
                  <span>飽和度 {Math.round(focusSegment.saturation_score * 100)}%</span>
                  <span>平均時速 {focusSegment.avg_speed} 公里</span>
                  <span>車流量 {focusSegment.vehicle_count} 輛</span>
                  <span>{focusSegment.lane_status}</span>
                  {timestamp && <span>資料時間 {timestamp}</span>}
                </div>
              ) : (
                <div className="text-xs text-[var(--muted-foreground)]">等待路網資料</div>
              )}
            </div>

            <div className="flex items-center gap-1.5">
              <button
                onClick={() => {
                  onClearFocus?.();
                  onBackToDashboard?.();
                }}
                className="flex items-center gap-1 px-2.5 py-1 rounded-sm text-xs border border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <ArrowLeft className="w-3 h-3" />
                返回儀表板
              </button>
              <button
                onClick={() => onClearFocus?.()}
                className="flex items-center gap-1 px-2.5 py-1 rounded-sm text-xs border border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <LayoutGrid className="w-3 h-3" />
                查看全部路段
              </button>
            </div>
          </div>
        </div>
      )}

      {advisories.length === 0 && !focusMode && (
        <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4 flex items-center justify-between gap-3 flex-wrap">
          <div className="space-y-1">
            <div className="text-sm font-medium">目前沒有事件建議書</div>
            <p className="text-sm text-[var(--muted-foreground)]">
              由「事件注入」頁注入 live_incidents.json 事件後，建議書會自動出現在這裡。
            </p>
          </div>
          {onOpenInjection && (
            <button
              onClick={onOpenInjection}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90 transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
            >
              <Siren className="w-3.5 h-3.5" />
              前往事件注入
            </button>
          )}
        </div>
      )}

      {advisories.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* 左側：地圖 + 事故路段即時影像 */}
          <div className="space-y-4">
            <div className="h-[340px]">
              <IncidentMap advisory={selectedAdvisory} />
            </div>
            <StreetCam advisory={selectedAdvisory} />
          </div>

          {/* 右側：事件卡片列表 */}
          <div className="space-y-3 overflow-y-auto max-h-[760px] pr-1">
            <div className="text-xs text-[var(--muted-foreground)] mb-1">
              {report.generated_at} — {report.processed}/{report.total_incidents} 件處理完成
            </div>
            {advisories.map((adv, idx) => (
              <AdvisoryCard
                key={idx}
                advisory={adv}
                isSelected={idx === selectedIdx}
                onSelect={() => setSelectedIdx(idx)}
              />
            ))}
          </div>
        </div>
      )}

      {/* 路段處置詳情：預警與自動路徑引導、飽和度趨勢、即時街景 */}
      <div className="space-y-2">
        {!focusMode && (
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--muted-foreground)] uppercase tracking-wide">
              路網即時詳情
            </h2>
            {timestamp && (
              <span className="text-xs text-[var(--muted-foreground)]">資料時間 {timestamp}</span>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
          <div className="space-y-4">
            <AlertTicker segments={tickerSegments} autoAdvisories={tickerAdvisories} />
            <TrendChart selectedSegment={detailSegment} simTime={timestamp} />
          </div>

          <div className="space-y-2">
            {/* 路段切換：預設追蹤最嚴重路段，可手動釘選 */}
            {abnormalSegments.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap">
                <button
                  onClick={() => pinSegment(null)}
                  title="自動追蹤最嚴重路段"
                  className={cn(
                    "flex items-center gap-1 px-2.5 py-1 rounded-sm text-xs border transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                    !focusMode && pinnedSegmentId === null
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
                    onClick={() => pinSegment(seg.segment_id)}
                    title={`飽和度 ${Math.round(seg.saturation_score * 100)}%`}
                    className={cn(
                      "px-2.5 py-1 rounded-sm text-xs whitespace-nowrap border transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                      detailSegment?.segment_id === seg.segment_id
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
      </div>
    </div>
  );
}
