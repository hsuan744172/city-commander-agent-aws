import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Bot, Eye, Loader2, ShieldAlert, Siren, X } from "lucide-react";
import ThreatGrid from "./ThreatGrid";
import CityMap3D from "./CityMap3D";
import SopTriggerPanel from "./SopTriggerPanel";
import StreamTimeline from "./StreamTimeline";
import { cn } from "../lib/utils";

/**
 * 即時儀表板
 *
 * 一個畫面看完路網現況：地圖 + 串流時間軸、即時路網監測、人流與信令主動偵測
 * （資料型條款 data_triggers，對應 SOP 第 3、4、6 條）。
 *
 * SOP 第 1 條的自動應變（auto_advisories）與僅監控清單（monitored_alerts）
 * 不在這裡展開，改由「路網即時監控」分頁與下方的自動預警彈窗呈現，
 * 儀表板才不會被長條列表撐出捲軸。
 *
 * 自動彈窗的摘要向 /api/alert-summary 取得（LLM 生成），門檻判定仍在後端程式，
 * 對應命題「摘要由 LLM 生成，門檻判定由程式運算」。
 */
export default function DashboardTab({ network, stream, onInspectSegment }) {
  const {
    segments,
    stations,
    timestamp,
    dataAsOf,
    monitoredAlerts,
    dataTriggers,
    thresholds,
  } = network;

  const [showAlert, setShowAlert] = useState(false);
  const [summary, setSummary] = useState(null);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const dismissedRef = useRef(null);

  // 異常特徵：異常路段組合或觸發條款有變化就視為新的預警，可以再次彈窗。
  // 原本用一個 boolean 記「已彈過」，整場 Demo 只會跳一次，
  // 之後時間推進出現新的癱瘓路段完全沒有提示。
  const signature = useMemo(() => {
    const abnormal = segments
      .filter((s) => s.level === "A" || s.level === "B")
      .map((s) => `${s.segment_id}:${s.level}`)
      .sort()
      .join(",");
    const sops = [...(dataTriggers?.triggered_numbers || [])].sort().join(",");
    return abnormal || sops ? `${abnormal}|${sops}` : "";
  }, [segments, dataTriggers]);

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true);
    try {
      const query = timestamp ? `?ts=${encodeURIComponent(timestamp)}` : "";
      const res = await fetch(`/api/alert-summary${query}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSummary(await res.json());
    } catch {
      setSummary(null);
    } finally {
      setLoadingSummary(false);
    }
  }, [timestamp]);

  useEffect(() => {
    if (!signature) return;
    if (dismissedRef.current === signature) return;
    setShowAlert(true);
    loadSummary();
  }, [signature, loadSummary]);

  const dismiss = () => {
    dismissedRef.current = signature;
    setShowAlert(false);
  };

  const openAlert = () => {
    setShowAlert(true);
    if (!summary) loadSummary();
  };

  return (
    // 填滿 App 給的剩餘高度：地圖與監測小卡吃掉可用空間，整頁不需要往下捲
    <div className="h-full min-h-0 flex flex-col">
      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-4 gap-4">
        {/* 左欄：地圖與時間軸緊貼成一體，兩者之間不留間距，
            共用外框圓角（地圖只圓上緣、時間軸只圓下緣） */}
        <div className="xl:col-span-3 flex flex-col min-h-0">
          <CityMap3D
            segments={segments}
            stations={stations}
            thresholds={thresholds}
            onSegmentClick={onInspectSegment}
            className="flex-1 min-h-0 rounded-b-none"
          />
          <StreamTimeline stream={stream} className="shrink-0 rounded-t-none border-t-0" />
        </div>

        {/* 右欄：即時路網監測，下方接資料型 SOP 的主動偵測 */}
        <div className="xl:col-span-1 flex flex-col gap-4 min-h-0">
          <ThreatGrid
            segments={segments}
            timestamp={timestamp}
            onSelect={onInspectSegment}
            className="flex-1 min-h-0"
          />
          <SopTriggerPanel
            dataTriggers={dataTriggers}
            dataAsOf={dataAsOf}
            className="shrink-0 max-h-[45%]"
          />
        </div>
      </div>

      {!showAlert && signature && (
        <button
          type="button"
          onClick={openAlert}
          className="fixed bottom-6 right-6 flex items-center gap-2 px-4 py-2.5 bg-[var(--status-error)] hover:opacity-90 text-[var(--primary-foreground)] rounded-full shadow-sm text-sm font-medium transition z-40 focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
        >
          <AlertTriangle className="w-4 h-4" />
          查看預警
        </button>
      )}

      {showAlert && (
        <AlertModal
          summary={summary}
          loading={loadingSummary}
          segments={segments}
          monitoredAlerts={monitoredAlerts}
          simTime={timestamp}
          onClose={dismiss}
        />
      )}
    </div>
  );
}

function AlertModal({ summary, loading, segments, monitoredAlerts, simTime, onClose }) {
  const closeRef = useRef(null);

  // Escape 關閉 + 開啟時把焦點移進對話框，鍵盤使用者才不會被困在背景
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    closeRef.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const triggerAlerts = segments.filter(
    (s) => s.is_trigger_segment && (s.level === "A" || s.level === "B"),
  );

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="alert-modal-title"
        className="bg-[var(--card)] border border-[var(--border)] rounded-xl p-6 max-w-2xl w-full shadow-sm max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-6 h-6 text-[var(--status-error)] shrink-0" />
            <h3 id="alert-modal-title" className="text-lg font-semibold text-[var(--status-error)]">
              路網異常自動預警
            </h3>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="關閉預警視窗"
            className="p-1.5 rounded-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* LLM 生成的摘要 */}
        <div className="mb-4 rounded-md bg-[var(--primary)]/10 p-4">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Bot className="w-3.5 h-3.5 text-[var(--primary)]" />
            <span className="text-[10px] font-semibold text-[var(--primary)]">
              AI 值班指揮官摘要
            </span>
            {summary?.source === "fallback" && (
              <span className="text-[10px] text-[var(--status-warning)]">
                （AI 未連線，以下為程式判定摘要）
              </span>
            )}
            {simTime && (
              <span className="ml-auto text-[10px] font-mono text-[var(--muted-foreground)]">
                {simTime}
              </span>
            )}
          </div>
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
              <Loader2 className="w-4 h-4 animate-spin" />
              產生摘要中...
            </div>
          ) : (
            <p className="text-sm leading-relaxed">
              {summary?.summary || "目前沒有可用的摘要。"}
            </p>
          )}
        </div>

        {/* 觸發路段：SOP 第 1 條只對這兩段啟動應變 */}
        {triggerAlerts.length > 0 && (
          <section className="mb-4">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Siren className="w-3.5 h-3.5 text-[var(--status-error)]" />
              <h4 className="text-xs font-semibold text-[var(--status-error)]">
                城市應變觸發路段（啟動長綠燈時制）
              </h4>
            </div>
            <ul className="space-y-1">
              {triggerAlerts.map((s) => (
                <li
                  key={s.segment_id}
                  className="text-sm bg-[var(--status-error)]/10 px-3 py-1.5 rounded-md"
                >
                  {s.road_name} — {s.level_description}，飽和度{" "}
                  {Math.round(s.saturation_score * 100)}%，時速 {s.avg_speed} 公里
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* SOP 第 3、4、6 條 */}
        {summary?.sop_triggers?.length > 0 && (
          <section className="mb-4">
            <h4 className="text-xs font-semibold text-[var(--status-warning)] mb-1.5">
              同時觸發之 SOP 條款
            </h4>
            <ul className="space-y-1.5">
              {summary.sop_triggers.map((t) => (
                <li
                  key={t.sop_number}
                  className="text-sm bg-[var(--status-warning)]/10 px-3 py-2 rounded-md"
                >
                  <span className="font-medium">
                    SOP 第 {t.sop_number} 條 {t.sop_title}
                  </span>
                  <div className="text-xs text-[var(--muted-foreground)] mt-0.5">{t.reason}</div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 非觸發路段：只做燈號顯示 */}
        {monitoredAlerts.length > 0 && (
          <section className="mb-4">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Eye className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
              <h4 className="text-xs font-semibold text-[var(--muted-foreground)]">
                其他達級別路段（依 SOP 第 1 條僅供燈號顯示，不啟動應變）
              </h4>
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              {monitoredAlerts
                .map((m) => `${m.road_name} ${m.level_description}`)
                .join("、")}
            </p>
          </section>
        )}

        {/* 引用條文原文 */}
        {summary?.sop_clauses?.length > 0 && (
          <details className="mb-4">
            <summary className="text-xs font-semibold text-[var(--muted-foreground)] cursor-pointer flex items-center gap-1.5">
              <ShieldAlert className="w-3.5 h-3.5" />
              判定依據的 SOP 條文原文（{summary.sop_clauses.length} 條）
            </summary>
            <div className="mt-2 space-y-2">
              {summary.sop_clauses.map((c) => (
                <pre
                  key={c.sop_number}
                  className="font-mono text-xs whitespace-pre-wrap bg-[var(--muted)] p-3 rounded-md text-[var(--muted-foreground)]"
                >
                  {c.text}
                </pre>
              ))}
            </div>
          </details>
        )}

        <button
          type="button"
          onClick={onClose}
          className="w-full py-2.5 bg-[var(--secondary)] hover:bg-[var(--accent)] text-[var(--secondary-foreground)] rounded-md text-sm font-medium transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
        >
          關閉
        </button>
      </div>
    </div>
  );
}
