import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileDown,
  Files,
  Loader2,
  Timer,
} from "lucide-react";
import AdvisoryCard from "./AdvisoryCard";
import IncidentMap from "./IncidentMap";
import IncidentReport from "./IncidentReport";
import StreetCam from "./StreetCam";
import { cn } from "../lib/utils";

const LEVEL_LABEL = {
  A: { text: "A 級", cls: "bg-[var(--status-error)] text-[var(--primary-foreground)]" },
  B: { text: "B 級", cls: "bg-[var(--status-warning)] text-[var(--primary-foreground)]" },
  Normal: {
    text: "正常",
    cls: "bg-[var(--status-success)] text-[var(--primary-foreground)]",
  },
};

/** 產製時間用約束 2 的 YYYY-MM-DD HH:MM，與路段報告一致。 */
function nowStamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
    `${pad(now.getHours())}:${pad(now.getMinutes())}`
  );
}

/**
 * 注入完成後的單頁事件處置工作區：地圖、街景、建議書與公眾通報保持在同一脈絡。
 *
 * 事件切換列是這一頁的入口：本次注入有幾筆事件、每筆的地點與分級、觸發哪些 SOP
 * 條款，一列就看完；右側只渲染當前選取那一筆的完整建議書，不再把 N 張卡片堆在
 * 同一條捲軸上（原本只有第一筆預設展開，看起來像「只有第一筆有分析」）。
 *
 * 匯出 PDF 沿用路段監控報告的機制：報告節點以 portal 掛到 #print-root，
 * 等兩幀畫完再送印，列印對話框關閉後清掉節點。
 */
export default function IncidentResponsePanel({ report }) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  // 有值時代表「報告已備妥、等著送印」；列印對話框關閉後清掉，節點不長駐 DOM
  const [printBundle, setPrintBundle] = useState(null);
  const advisories = report?.advisories || [];
  const selectedAdvisory = advisories[selectedIdx] || advisories[0] || null;

  useEffect(() => {
    setSelectedIdx(0);
    setPrintBundle(null);
  }, [report]);

  // 報告節點掛上後等瀏覽器畫完兩幀再送印，避免表格還沒排版就開列印對話框
  useEffect(() => {
    if (!printBundle) return undefined;
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
  }, [printBundle]);

  useEffect(() => {
    const clear = () => setPrintBundle(null);
    window.addEventListener("afterprint", clear);
    return () => window.removeEventListener("afterprint", clear);
  }, []);

  const total = advisories.length;

  const exportSingle = () => {
    if (!selectedAdvisory) return;
    setPrintBundle({
      generatedAt: nowStamp(),
      pages: [{ advisory: selectedAdvisory, seq: selectedIdx + 1, total }],
    });
  };

  const exportAll = () => {
    if (total === 0) return;
    setPrintBundle({
      generatedAt: nowStamp(),
      pages: advisories.map((advisory, index) => ({
        advisory,
        seq: index + 1,
        total,
      })),
    });
  };

  const switcherItems = useMemo(
    () =>
      advisories.map((advisory, index) => {
        const eid = advisory.event_identification || {};
        return {
          key: advisory.event_id || `event-${index}`,
          index,
          eventId: advisory.event_id || `事件 ${index + 1}`,
          location: eid.location || eid.affected_segment || "",
          level: advisory.traffic_classification?.max_level,
          sopNumbers: (eid.triggered_sop_articles || []).map((item) => item.sop_number),
          failed: Boolean(advisory.error),
        };
      }),
    [advisories],
  );

  if (!report) return null;

  return (
    <section className="space-y-4" aria-labelledby="incident-response-title">
      <div className="flex items-start justify-between gap-3 flex-wrap rounded-lg border border-[var(--status-success)]/40 bg-[var(--status-success)]/10 p-4">
        <div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-[var(--status-success)]" />
            <h2 id="incident-response-title" className="text-lg font-semibold">
              即時事件處置建議書
            </h2>
          </div>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            已完成事件辨識、SOP 比對、替代路徑、恢復時間與公眾通報，可直接在本頁執行處置。
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap text-xs text-[var(--muted-foreground)]">
          {report.generated_at && <span>產出時間 {report.generated_at}</span>}
          <span>
            {report.processed ?? 0}/{report.total_incidents ?? advisories.length} 件完成
          </span>
          {report.elapsed_seconds != null && (
            <span
              title="從事件注入到建議書完成的端到端時間"
              className={cn(
                "flex items-center gap-1 rounded-sm px-2 py-1 font-medium",
                report.within_budget
                  ? "bg-[var(--status-success)]/20 text-[var(--status-success)]"
                  : "bg-[var(--status-error)]/15 text-[var(--status-error)]",
              )}
            >
              <Timer className="w-3 h-3" />
              {report.elapsed_seconds} 秒 / 預算 {report.budget_seconds ?? 60} 秒
            </span>
          )}
        </div>
      </div>

      {advisories.length === 0 ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 text-sm text-[var(--muted-foreground)]">
          本次注入未產出可顯示的事件建議書，請查看上方失敗數量或後端紀錄。
        </div>
      ) : (
        <>
          {/* ── 事件切換列：每筆事件都有獨立報告，先在這裡講清楚 ────────── */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm">
                本次注入共{" "}
                <span className="font-bold text-[var(--primary)]">{total}</span>{" "}
                筆事件，點選下方事件即可查看該筆完整建議書（目前為第 {selectedIdx + 1} 筆）。
              </p>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={exportSingle}
                  disabled={!selectedAdvisory || Boolean(printBundle)}
                  title="只輸出當前選取事件的建議書（於列印視窗選擇另存為 PDF）"
                  className="flex items-center gap-1 rounded-sm border border-[var(--primary)] bg-[var(--primary)] px-2.5 py-1 text-xs font-medium text-[var(--primary-foreground)] transition hover:opacity-90 disabled:pointer-events-none disabled:opacity-50 focus-visible:ring-[3px] focus-visible:ring-[var(--ring)]"
                >
                  {printBundle?.pages?.length === 1 ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <FileDown className="h-3 w-3" />
                  )}
                  匯出本事件 PDF
                </button>
                <button
                  type="button"
                  onClick={exportAll}
                  disabled={total === 0 || Boolean(printBundle)}
                  title="輸出全部事件建議書，每筆事件一頁（於列印視窗選擇另存為 PDF）"
                  className="flex items-center gap-1 rounded-sm border border-[var(--border)] bg-[var(--muted)] px-2.5 py-1 text-xs font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--accent)] disabled:pointer-events-none disabled:opacity-50 focus-visible:ring-[3px] focus-visible:ring-[var(--ring)]"
                >
                  {printBundle && printBundle.pages.length > 1 ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Files className="h-3 w-3" />
                  )}
                  匯出全部事件 PDF（{total} 頁）
                </button>
              </div>
            </div>

            <div
              className="flex flex-wrap gap-2"
              role="group"
              aria-label={`事件切換，共 ${total} 筆`}
            >
              {switcherItems.map((item) => {
                const active = item.index === selectedIdx;
                const level = LEVEL_LABEL[item.level] || LEVEL_LABEL.Normal;
                return (
                  <button
                    key={item.key}
                    type="button"
                    aria-current={active ? "true" : undefined}
                    onClick={() => setSelectedIdx(item.index)}
                    className={cn(
                      "min-w-[200px] flex-1 rounded-md border px-3 py-2 text-left transition focus-visible:ring-[3px] focus-visible:ring-[var(--ring)]",
                      active
                        ? "border-[var(--primary)] bg-[var(--primary)]/10 ring-2 ring-[var(--ring)]/30"
                        : "border-[var(--border)] bg-[var(--background)] hover:bg-[var(--accent)]/50",
                    )}
                  >
                    <div className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          "flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-[10px] font-bold",
                          active
                            ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                            : "bg-[var(--secondary)] text-[var(--secondary-foreground)]",
                        )}
                      >
                        {item.index + 1}
                      </span>
                      <span className="font-mono text-xs font-bold">{item.eventId}</span>
                      {item.failed ? (
                        <span className="ml-auto flex items-center gap-1 rounded-sm bg-[var(--status-warning)]/20 px-1.5 py-0.5 text-[10px] font-medium text-[var(--status-warning)]">
                          <AlertTriangle className="h-3 w-3" />
                          處理異常
                        </span>
                      ) : (
                        <span
                          className={cn(
                            "ml-auto rounded-sm px-1.5 py-0.5 text-[10px] font-bold",
                            level.cls,
                          )}
                        >
                          {level.text}
                        </span>
                      )}
                    </div>

                    {item.location && (
                      <div className="mt-1 truncate text-xs text-[var(--muted-foreground)]">
                        {item.location}
                      </div>
                    )}

                    <div className="mt-1 flex flex-wrap gap-1">
                      {item.sopNumbers.length > 0 ? (
                        item.sopNumbers.map((number) => (
                          <span
                            key={number}
                            className="rounded-sm bg-[var(--status-warning)]/20 px-1.5 py-0.5 text-[10px] font-medium text-[var(--status-warning)]"
                          >
                            SOP {number}
                          </span>
                        ))
                      ) : (
                        <span className="text-[10px] text-[var(--muted-foreground)]">
                          {item.failed ? "無條款判定結果" : "未觸發事件型條款"}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
            <div className="space-y-4 xl:sticky xl:top-4">
              <div className="h-[340px]">
                <IncidentMap advisory={selectedAdvisory} />
              </div>
              <StreetCam advisory={selectedAdvisory} />
            </div>

            <div className="space-y-3">
              {selectedAdvisory && (
                <AdvisoryCard
                  key={selectedAdvisory.event_id || selectedIdx}
                  advisory={selectedAdvisory}
                  isSelected
                  onSelect={() => setSelectedIdx(selectedIdx)}
                  defaultExpanded
                />
              )}
            </div>
          </div>
        </>
      )}

      {printBundle && (
        <IncidentReport
          pages={printBundle.pages}
          generatedAt={printBundle.generatedAt}
        />
      )}
    </section>
  );
}
