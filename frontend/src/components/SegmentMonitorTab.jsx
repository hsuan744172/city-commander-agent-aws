import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Bot,
  FileDown,
  Loader2,
  MapPinned,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import AutoAdvisoryPanel from "./AutoAdvisoryPanel";
import SegmentReport from "./SegmentReport";
import StreetCam from "./StreetCam";
import TrendChart from "./TrendChart";
import useSegmentAlertSummary from "../lib/useSegmentAlertSummary";
import useTrendSeries from "../lib/useTrendSeries";
import { cn } from "../lib/utils";

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

/** 產製時間一律用約束 2 的 YYYY-MM-DD HH:MM，與資料時間格式一致。 */
function nowStamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
    `${pad(now.getHours())}:${pad(now.getMinutes())}`
  );
}

/**
 * 把攝影機快照讀成 data URL 再放進報告。
 *
 * 報告節點在螢幕上是隱藏的，直接寫 <img src="/api/..."> 有機會在列印對話框開啟時
 * 還沒下載完，印出來就是空框。改成先抓成 data URL，確認拿到畫面才進列印流程。
 * 端點是後端同源代理，不論鏡頭是直播或快照模式都取得到單張畫面。
 *
 * 這是退路：報告優先採用螢幕實際畫面的截圖（見 captureScreenSnapshot）。
 */
async function loadSnapshotDataUrl(path) {
  const res = await fetch(`${path}?_=${Date.now()}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** 這一幀的畫面來源狀態，用於在報告誠實標注（合成示意畫面不得標成真實影像）。 */
async function loadFrameInfo(path) {
  if (!path) return null;
  try {
    const res = await fetch(`${path}?_=${Date.now()}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * 取得報告要嵌入的路段影像。
 *
 * 順序有意義：
 *   1. 截取螢幕上正在播放的那一幀 — 報告與值班人員當下看到的畫面完全一致，
 *      HLS 直播鏡頭也因此拿到真正的直播畫面，而不是來源不同的另一張靜態快照。
 *   2. 截圖不可用時（尚未解碼、canvas 被跨來源污染）才退回後端 /snapshot 代理。
 *
 * 一併回傳來源標注資訊，讓報告能區分「真實現地影像」與「系統合成示意畫面」。
 */
async function resolveReportSnapshot(camera) {
  if (!camera) return { dataUrl: null, meta: null };

  const captured = typeof camera.capture === "function" ? camera.capture() : null;
  if (captured?.dataUrl) {
    return { dataUrl: captured.dataUrl, meta: captured };
  }

  if (!camera.snapshot_path) return { dataUrl: null, meta: null };

  const [dataUrl, info] = await Promise.all([
    loadSnapshotDataUrl(camera.snapshot_path),
    loadFrameInfo(camera.frame_path),
  ]);

  return {
    dataUrl,
    meta: {
      method: "proxy",
      mode: camera.mode || "snapshot",
      is_mock: Boolean(info?.is_mock),
      captured_at: info?.captured_at || null,
      age_seconds: info?.age_seconds ?? null,
    },
  };
}

/**
 * 路段即時監控（單一路段，儀表板的下鑽檢視）
 *
 * 唯一入口是從即時儀表板點擊地圖路段或右側路段小卡穿透進來，導覽列沒有頁籤，
 * 因此本頁不提供路段切換與自動追蹤；路段身分（路名、代號、分級）只在頁首標示一次，
 * 趨勢圖與影像面板不再重複。
 *
 * 定位對應命題模組 1（動態時序監測）：主動偵測、預警與預防性處置建議，
 * 並可將畫面資訊匯出為 PDF 監控報告。事件注入產出的「交控中心建議書」與多語
 * 民眾簡訊屬模組 2，留在注入頁原地處置。
 */
export default function SegmentMonitorTab({
  network,
  selectedSegmentId = null,
  onBackToDashboard,
}) {
  const { segments, timestamp, autoAdvisories, monitoredAlerts, thresholds } = network;

  const [camera, setCamera] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  // 有值時代表「報告已備妥、等著送印」；列印對話框關閉後清掉，節點不長駐 DOM
  const [reportBundle, setReportBundle] = useState(null);

  const segment = useMemo(
    () => segments.find((s) => s.segment_id === selectedSegmentId) || null,
    [segments, selectedSegmentId],
  );

  const advisories = useMemo(
    () => autoAdvisories.filter((a) => a.segment_id === selectedSegmentId),
    [autoAdvisories, selectedSegmentId],
  );

  // 非 SOP 第 1 條城市應變觸發路段達 A/B 級時，會落在 monitored_alerts。
  // 這裡必須帶入「本路段」那一筆，否則上方掛著 A 級 Tag、下方卻無任何判定說明。
  const monitoredAlert = useMemo(
    () => monitoredAlerts.find((m) => m.segment_id === selectedSegmentId) || null,
    [monitoredAlerts, selectedSegmentId],
  );

  // 觸發路段名單來自後端 is_trigger_segment，前端不寫死路段名稱
  const triggerSegmentNames = useMemo(
    () => segments.filter((s) => s.is_trigger_segment).map((s) => s.road_name),
    [segments],
  );

  const hasAlert = segment?.level === "A" || segment?.level === "B";

  const { data: trendData, loading: trendLoading } = useTrendSeries(timestamp || null);
  const {
    summary: alertSummary,
    loading: summaryLoading,
  } = useSegmentAlertSummary(segment?.segment_id || null, timestamp || null, hasAlert);

  const handleCameraChange = useCallback((next) => setCamera(next), []);

  const exportReport = async () => {
    if (!segment || !hasAlert) return;
    setExporting(true);
    setExportError("");
    try {
      let snapshotDataUrl = null;
      let snapshotMeta = null;
      try {
        const shot = await resolveReportSnapshot(camera);
        snapshotDataUrl = shot.dataUrl;
        snapshotMeta = shot.meta;
      } catch {
        // 影像取不到不該擋住整份報告，報告內會註明無可用影像
        snapshotDataUrl = null;
        snapshotMeta = null;
      }
      setReportBundle({ snapshotDataUrl, snapshotMeta, generatedAt: nowStamp() });
    } catch (err) {
      setExportError(err?.message || "報告產製失敗");
    } finally {
      setExporting(false);
    }
  };

  // 報告節點掛上後等瀏覽器畫完兩幀再送印，避免趨勢圖還沒繪製就開列印對話框
  useEffect(() => {
    if (!reportBundle) return undefined;
    let cancelled = false;
    const outer = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!cancelled) window.print();
      });
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(outer);
    };
  }, [reportBundle]);

  useEffect(() => {
    const clear = () => setReportBundle(null);
    window.addEventListener("afterprint", clear);
    return () => window.removeEventListener("afterprint", clear);
  }, []);

  if (!segment) {
    return (
      <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-8 flex flex-col items-center justify-center gap-3 text-center">
        <MapPinned className="w-8 h-8 text-[var(--muted-foreground)] opacity-40" />
        <p className="text-sm text-[var(--muted-foreground)]">
          尚未指定監控路段。請於即時儀表板點擊地圖路段或右側路段小卡進入本頁。
        </p>
        <button
          type="button"
          onClick={onBackToDashboard}
          className="flex items-center gap-1 px-3 py-1.5 rounded-sm text-xs border border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
        >
          <ArrowLeft className="w-3 h-3" />
          前往即時儀表板
        </button>
      </div>
    );
  }

  const badge = levelBadge(segment.level);
  const trend = alertSummary?.trend?.available ? alertSummary.trend : null;

  return (
    <div className="space-y-4">
      <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4 shadow-sm">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-[var(--primary)]" />
              <span className="text-sm font-semibold text-[var(--muted-foreground)] uppercase tracking-wide">
                路段即時監控
              </span>
            </div>

            {/* 路段身分只在這裡標示一次 */}
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-bold">{segment.road_name}</h2>
              <span className="text-xs font-mono text-[var(--muted-foreground)]">
                {segment.segment_id}
              </span>
              <span className={cn("text-xs px-2 py-0.5 rounded-sm font-bold", badge.cls)}>
                {badge.text}
              </span>
            </div>

            <div className="flex items-center gap-3 text-xs text-[var(--muted-foreground)] flex-wrap">
              <span>飽和度 {Math.round(segment.saturation_score * 100)}%</span>
              <span>平均時速 {segment.avg_speed} 公里</span>
              <span>車流量 {segment.vehicle_count} 輛</span>
              <span>{segment.lane_status_label || segment.lane_status}</span>
              {timestamp && <span>資料時間 {timestamp}</span>}
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            {hasAlert && (
              <button
                type="button"
                onClick={exportReport}
                // 研判還在產生時就送印，報告會少掉「AI 研判」與「條文原文」兩節
                disabled={exporting || summaryLoading || Boolean(reportBundle)}
                title={
                  summaryLoading
                    ? "AI 研判產生中，完成後即可匯出"
                    : "產製 PDF 監控報告（於列印視窗選擇另存為 PDF）"
                }
                className="flex items-center gap-1 px-2.5 py-1 rounded-sm text-xs font-medium border border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90 transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                {exporting || summaryLoading || reportBundle ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <FileDown className="w-3 h-3" />
                )}
                匯出 PDF 報告
              </button>
            )}
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

        {exportError && (
          <p className="mt-2 text-xs text-[var(--status-error)]">
            報告產製失敗（{exportError}）
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
        <div className="space-y-4">
          <AutoAdvisoryPanel
            advisories={advisories}
            monitoredAlert={monitoredAlert}
            triggerSegmentNames={triggerSegmentNames}
          />

          {hasAlert && (
            <AiJudgementCard
              summary={alertSummary}
              loading={summaryLoading}
              trend={trend}
            />
          )}

          <TrendChart
            selectedSegment={segment}
            data={trendData}
            loading={trendLoading}
            thresholds={thresholds}
          />
        </div>

        <StreetCam
          segmentId={segment.segment_id}
          label=""
          title="路段即時影像"
          emptyHint="等待路網資料"
          onCameraChange={handleCameraChange}
        />
      </div>

      {reportBundle && (
        <SegmentReport
          segment={segment}
          segments={segments}
          advisory={advisories[0] || null}
          monitoredAlert={monitoredAlert}
          thresholds={thresholds}
          simTime={timestamp}
          trendData={trendData}
          aiSummary={alertSummary}
          camera={camera}
          snapshotDataUrl={reportBundle.snapshotDataUrl}
          snapshotMeta={reportBundle.snapshotMeta}
          generatedAt={reportBundle.generatedAt}
          triggerSegmentNames={triggerSegmentNames}
        />
      )}
    </div>
  );
}

/**
 * AI 值班指揮官研判
 *
 * 摘要由語言模型撰寫，趨勢統計與門檻判定都在後端程式算完才交給模型，
 * 對應命題「摘要由 LLM 生成，門檻判定由程式運算」。畫面與匯出報告共用同一份內容。
 */
function AiJudgementCard({ summary, loading, trend }) {
  const paragraphs = String(summary?.summary || "")
    .split(/\n+/)
    .filter(Boolean);

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <Bot className="w-4 h-4 text-[var(--primary)]" />
        <h2 className="text-sm font-semibold">AI 值班指揮官研判</h2>
        {summary?.source === "fallback" && (
          <span className="text-xs text-[var(--status-warning)]">
            AI 未連線，以下為程式判定直述
          </span>
        )}
      </div>

      {trend && (
        <div className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
          {trend.direction === "falling" ? (
            <TrendingDown className="w-3.5 h-3.5 text-[var(--status-success)]" />
          ) : (
            <TrendingUp
              className={cn(
                "w-3.5 h-3.5",
                trend.direction === "rising"
                  ? "text-[var(--status-error)]"
                  : "text-[var(--muted-foreground)]",
              )}
            />
          )}
          <span>
            近 {trend.window_minutes} 分鐘飽和度
            {trend.direction_label} {Math.abs(trend.delta_percentage_points)} 個百分點
            （{Math.round(trend.first_saturation_score * 100)}% →{" "}
            {Math.round(trend.current_saturation_score * 100)}%）
          </span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="w-4 h-4 animate-spin" />
          產生研判中...
        </div>
      ) : paragraphs.length > 0 ? (
        <div className="space-y-1.5">
          {paragraphs.map((paragraph, index) => (
            <p key={index} className="text-sm leading-relaxed">
              {paragraph}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-sm text-[var(--muted-foreground)]">目前沒有可用的研判內容。</p>
      )}
    </div>
  );
}
