import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  FileJson,
  Lock,
  History,
  Minus,
  Upload,
  Zap,
} from "lucide-react";
import { cn } from "../lib/utils";
import ConfirmDialog from "./ConfirmDialog";
import IncidentResponsePanel from "./IncidentResponsePanel";
import {
  CONFIRMATION_LABELS,
  fetchInjectionCatalog,
  fetchRecentInjections,
  injectIncidents,
  previewIncidents,
  previewUploadedIncidents,
  templateToEvent,
  withUniqueEventId,
} from "../lib/incidentInjection";

const SEVERITY_STYLES = {
  Critical: { icon: AlertTriangle, cls: "text-[var(--status-error)] bg-[var(--status-error)]/10" },
  High: { icon: ArrowUp, cls: "text-[var(--status-warning)] bg-[var(--status-warning)]/10" },
  Medium: { icon: Minus, cls: "text-[var(--status-idle)] bg-[var(--status-idle)]/10" },
};

const CATEGORY_STYLES = {
  Road_Disruption: "text-[var(--status-error)] bg-[var(--status-error)]/10 border-[var(--status-error)]/30",
  Crowd_Surge: "text-[var(--status-info)] bg-[var(--status-info)]/10 border-[var(--status-info)]/30",
  Signal_Failure: "text-[var(--status-warning)] bg-[var(--status-warning)]/10 border-[var(--status-warning)]/30",
};

const CARD = "bg-[var(--card)] rounded-lg border border-[var(--border)] p-4";
const SECTION_HEADING =
  "text-sm font-semibold text-[var(--muted-foreground)] uppercase tracking-wide";
const FIELD =
  "w-full rounded-sm border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm " +
  "focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]";

function eventsFromDraft(draft) {
  const value = JSON.parse(draft);
  if (Array.isArray(value)) return value;
  if (value && Array.isArray(value.incidents)) return value.incidents;
  throw new SyntaxError("頂層必須是事件陣列");
}

function draftFromEvents(events) {
  return JSON.stringify(events, null, 2);
}

/** 去掉契約層自行推導的欄位，讓編輯器內容維持可再次注入的形狀。 */
function editableRecord(record) {
  const clean = { ...record };
  delete clean.category;
  delete clean.original_index;
  return Object.fromEntries(Object.entries(clean).filter(([, value]) => value != null));
}

/**
 * 事件注入介面（管理員）
 *
 * 三段式流程：挑選/編輯 live_incidents.json 內容 → 驗證取得預覽 → 在確認對話框勾選後注入。
 * 所有驗證與分類都由後端契約層負責，這裡只呈現結果與收集確認。
 *
 * 注入前確認從驗證卡片裡的勾選方塊改成跳出式對話框：注入會改動全系統狀態，
 * 確認這一步不該混在可捲動的長卡片中被順手滑過，改由對話框把動作攔在眼前。
 */
export default function InjectionTab() {
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [draft, setDraft] = useState("");
  const [simTime, setSimTime] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [confirmed, setConfirmed] = useState([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // 上傳失敗時要提示「已保留上一份有效預覽」，與編輯內容出錯的語意不同
  const [uploadFailed, setUploadFailed] = useState(false);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [showReferences, setShowReferences] = useState(false);
  // "compose"＝注入設定，"report"＝處置建議書；兩者共用滿高區域，切換不重建內容
  const [view, setView] = useState("compose");
  const fileRef = useRef(null);

  const loadHistory = useCallback(async () => {
    try {
      const body = await fetchRecentInjections({ limit: 5 });
      setHistory(body.injections || []);
    } catch {
      // 紀錄只是輔助資訊，讀不到不影響注入流程
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const body = await fetchInjectionCatalog();
        if (cancelled) return;
        setCatalog(body);
        // 預設帶入 data/live_incidents.json 的完整內容，管理員可直接注入或先修改
        if (body.templates?.length) {
          setDraft(draftFromEvents(body.templates.map(templateToEvent)));
        }
      } catch (exc) {
        if (!cancelled) setCatalogError(exc.message);
      }
    })();
    loadHistory();
    return () => {
      cancelled = true;
    };
  }, [loadHistory]);

  // 內容或對齊時間一改動，之前的驗證就作廢；
  // 後端注入時也會用 preview_hash 再擋一次，避免驗證後偷改內容。
  const invalidatePreview = () => {
    setPreview(null);
    setConfirmed([]);
    // 對話框上的確認事項是綁在剛剛那份預覽上的，預覽作廢就一併收掉
    setConfirmOpen(false);
    setError(null);
    setResult(null);
    setUploadFailed(false);
    setView("compose");
  };

  const updateDraft = (text) => {
    setDraft(text);
    invalidatePreview();
  };

  const updateSimTime = (value) => {
    setSimTime(value);
    invalidatePreview();
  };

  const appendTemplate = (template) => {
    let events = [];
    try {
      events = eventsFromDraft(draft || "[]");
    } catch {
      events = [];
    }
    const existingIds = events.map((event) => event?.event_id).filter(Boolean);
    updateDraft(
      draftFromEvents([...events, withUniqueEventId(templateToEvent(template), existingIds)]),
    );
  };

  const runPreview = async () => {
    let payload;
    try {
      payload = eventsFromDraft(draft);
    } catch {
      setPreview(null);
      setError({ message: "JSON 無法解析，請確認內容為事件陣列", details: [] });
      return;
    }

    setBusy("preview");
    setError(null);
    setResult(null);
    setUploadFailed(false);
    try {
      const next = await previewIncidents({ payload, simTime });
      setPreview(next);
      setConfirmed([]);
    } catch (exc) {
      setPreview(null);
      setError(exc);
    } finally {
      setBusy("");
    }
  };

  const uploadFile = async (file) => {
    if (!file) return;
    setBusy("preview");
    setError(null);
    setResult(null);
    try {
      const next = await previewUploadedIncidents({ file, simTime });
      setPreview(next);
      setConfirmed([]);
      setDraft(draftFromEvents(next.normalized_payload.incidents.map(editableRecord)));
    } catch (exc) {
      // 新檔案驗證失敗不動既有內容，上一份有效預覽保留，錯誤另行顯示。
      setError(exc);
      setUploadFailed(true);
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const runInject = async () => {
    if (!preview) return;
    setBusy("inject");
    setError(null);
    try {
      const body = await injectIncidents({
        payload: preview.normalized_payload.incidents.map(editableRecord),
        previewHash: preview.preview_hash,
        confirmations: confirmed,
        simTime: preview.simulation_clock_time,
        adminToken,
      });
      setResult(body);
      // 注入成功後直接把滿高區域讓給建議書，不用往下滑
      if (body?.report) setView("report");
      loadHistory();
    } catch (exc) {
      setError(exc);
    } finally {
      setBusy("");
    }
  };

  // 對話框按下確認：先收掉對話框再送出，注入中的狀態由「注入系統」鈕接手顯示
  const confirmInject = () => {
    if (busy !== "") return;
    setConfirmOpen(false);
    runInject();
  };

  const cancelInject = () => {
    setConfirmOpen(false);
    // 取消等於整組確認重新來一次，避免下次開啟時帶著上次的勾選
    setConfirmed([]);
  };

  const toggleConfirmation = (key) => {
    setConfirmed((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  };

  const required = preview?.required_confirmations || [];
  const readyToInject = Boolean(preview) && required.every((key) => confirmed.includes(key));
  const summaries = preview?.event_summaries || [];
  const eventCount = useMemo(() => {
    try {
      return eventsFromDraft(draft || "[]").length;
    } catch {
      return null;
    }
  }, [draft]);

  const hasReport = Boolean(result?.report);
  const showReport = hasReport && view === "report";
  const advisoryCount = result?.report?.advisories?.length ?? result?.report?.processed ?? 0;
  // 第一步的內部進度：讓流程列直接說出「下一個動作是什麼」，不必再靠額外提示文字
  // 確認事項改在對話框內勾選，所以只有對話框開著且還沒勾完才叫「待確認」，
  // 其餘只要有有效預覽，下一個動作就是注入。
  const composeHint = hasReport
    ? "已注入"
    : !preview
      ? "待驗證"
      : confirmOpen && !readyToInject
        ? "待確認"
        : "可注入";

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <div className="shrink-0 space-y-3 empty:hidden">
        {catalogError && <Banner tone="error" text={`無法載入注入目錄：${catalogError}`} />}
        {catalog?.template_error && <Banner tone="warning" text={catalog.template_error} />}
        {catalog?.source_errors?.length > 0 && (
          <Banner tone="warning" text={`資料來源異常：${catalog.source_errors.join("；")}`} />
        )}
      </div>

      {/*
        流程列取代原本的兩顆切換鈕：從頭到尾都在，說明「現在在哪一步、下一步做什麼」。
        第二步在注入完成前是鎖住的狀態，注入成功後自動成為當前步驟，兩步的內容都保持掛載。
      */}
      <nav aria-label="事件注入流程" className="shrink-0 flex items-center gap-1.5">
        <FlowStep
          index={1}
          label="編輯與驗證"
          hint={composeHint}
          current={!showReport}
          done={hasReport}
          onClick={() => setView("compose")}
        />
        <ChevronRight className="w-3.5 h-3.5 shrink-0 text-[var(--muted-foreground)]" />
        <FlowStep
          index={2}
          label="處置建議書"
          hint={hasReport ? `${advisoryCount} 件` : "注入後開放"}
          current={showReport}
          locked={!hasReport}
          onClick={() => setView("report")}
        />
      </nav>

      <div
        className={cn(
          "flex-1 min-h-0 flex flex-col xl:flex-row gap-4 overflow-y-auto xl:overflow-hidden",
          showReport && "hidden",
        )}
      >
        {/* 左側：來源與編輯 */}
        <div className="xl:flex-1 xl:min-h-0 flex flex-col gap-4 xl:overflow-y-auto">
          <div className={cn(CARD, "shrink-0")}>
            <h3 className={cn(SECTION_HEADING, "mb-3")}>事件範本</h3>
            <div className="flex flex-wrap gap-1.5">
              {(catalog?.templates || []).map((template) => (
                <button
                  key={template.event_id}
                  onClick={() => appendTemplate(template)}
                  title={template.description}
                  className={cn(
                    "flex items-center gap-1.5 px-2.5 py-1 rounded-sm text-xs border transition",
                    "hover:bg-[var(--accent)]/50",
                    CATEGORY_STYLES[template._category] || "border-[var(--border)]",
                  )}
                >
                  <FileJson className="w-3 h-3" />
                  {template._category_label}
                  <span className="font-mono text-[10px] opacity-70">
                    {template.affected_segment}
                  </span>
                </button>
              ))}
              {catalog?.templates?.length > 0 && (
                <button
                  onClick={() => updateDraft(draftFromEvents(catalog.templates.map(templateToEvent)))}
                  className="px-2.5 py-1 rounded-sm text-xs border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50 transition"
                >
                  重設為完整範本
                </button>
              )}
            </div>
          </div>

          <div className={cn(CARD, "xl:flex-1 xl:min-h-0 flex flex-col")}>
            <div className="shrink-0 flex items-center justify-between gap-2 mb-2">
              <h3 className={SECTION_HEADING}>注入內容</h3>
              <span className="text-xs text-[var(--muted-foreground)]">
                {eventCount === null ? "JSON 格式錯誤" : `${eventCount} 件`}
                {catalog?.max_records ? ` / 上限 ${catalog.max_records} 件` : ""}
              </span>
            </div>

            {/* 編輯區吃掉左欄剩餘高度，讓整頁不需要外層捲動 */}
            <textarea
              value={draft}
              onChange={(event) => updateDraft(event.target.value)}
              spellCheck={false}
              rows={12}
              aria-label="事件注入內容 JSON"
              className={cn(
                FIELD,
                "font-mono text-xs leading-relaxed resize-none xl:flex-1 xl:min-h-[140px]",
              )}
              placeholder='[{"event_id": "...", "type": "...", "affected_segment": "RD_TPE_002", ...}]'
            />

            <div className="shrink-0 grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
              <label className="space-y-1">
                <span className="text-xs text-[var(--muted-foreground)]">
                  對齊模擬時間（留空＝當下）
                </span>
                <input
                  value={simTime}
                  onChange={(event) => updateSimTime(event.target.value)}
                  placeholder={catalog?.sim_time || "YYYY-MM-DD HH:MM"}
                  className={cn(FIELD, "font-mono text-xs")}
                />
              </label>
              {catalog?.requires_admin_token && (
                <label className="space-y-1">
                  <span className="text-xs text-[var(--muted-foreground)]">管理員權杖</span>
                  <input
                    value={adminToken}
                    onChange={(event) => setAdminToken(event.target.value)}
                    type="password"
                    autoComplete="off"
                    className={cn(FIELD, "text-xs")}
                  />
                </label>
              )}
            </div>

            <div className="shrink-0 flex items-center gap-2 mt-3 flex-wrap">
              <button
                onClick={runPreview}
                disabled={busy !== "" || !draft.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-[var(--secondary)] text-[var(--secondary-foreground)] hover:bg-[var(--accent)] transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <ClipboardCheck className="w-3.5 h-3.5" />
                {busy === "preview" ? "驗證中…" : "驗證事件"}
              </button>

              <button
                onClick={() => fileRef.current?.click()}
                disabled={busy !== ""}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50 transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <Upload className="w-3.5 h-3.5" />
                上傳 JSON 檔
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".json,application/json"
                onChange={(event) => uploadFile(event.target.files?.[0])}
                className="hidden"
              />

              {/* 驗證過就能按；勾選確認事項移到對話框裡完成 */}
              <button
                onClick={() => setConfirmOpen(true)}
                disabled={!preview || busy !== ""}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90 transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <Zap className="w-3.5 h-3.5" />
                {busy === "inject" ? "注入中…" : "注入系統"}
              </button>
            </div>
          </div>

          <div className="shrink-0">
            <ReferenceCard
              catalog={catalog}
              open={showReferences}
              onToggle={() => setShowReferences((open) => !open)}
            />
          </div>
        </div>

        {/* 右側：驗證結果與紀錄 */}
        <div className="xl:flex-1 xl:min-h-0 space-y-4 xl:overflow-y-auto">
          {error && (
            <ErrorCard error={error} keptPreview={uploadFailed && Boolean(preview)} />
          )}

          {result && (
            <div className={cn(CARD, "border-[var(--status-success)]/40")}>
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle2 className="w-4 h-4 text-[var(--status-success)]" />
                <h3 className="text-sm font-semibold text-[var(--status-success)]">注入完成</h3>
              </div>
              <div className="text-sm text-[var(--muted-foreground)] space-y-1">
                <div>
                  處理 {result.report?.processed ?? 0} 件、失敗 {result.report?.failed ?? 0} 件，
                  建議書時間 {result.report?.generated_at || "-"}
                </div>
                <div className="font-mono text-xs">{result.injection?.injection_id}</div>
              </div>
            </div>
          )}

          {preview ? (
            <div className={CARD}>
              <div className="flex items-center justify-between gap-2 mb-3">
                <h3 className={SECTION_HEADING}>驗證通過</h3>
                <span className="font-mono text-xs text-[var(--muted-foreground)]">
                  {preview.preview_id}
                </span>
              </div>

              <div className="text-xs text-[var(--muted-foreground)] mb-3">
                {summaries.length} 件事件，對齊模擬時間 {preview.simulation_clock_time}
              </div>

              {preview.contains_future_event && (
                <Banner
                  tone="warning"
                  text="內容包含晚於當下模擬時間的事件，注入後會提前套用該時段的路網資料。"
                />
              )}

              <div className="space-y-2 mt-3">
                {summaries.map((summary) => (
                  <EventSummaryRow key={summary.event_id} summary={summary} />
                ))}
              </div>
            </div>
          ) : (
            !error && (
              <div className={cn(CARD, "text-sm text-[var(--muted-foreground)]")}>
                尚未驗證。編輯或上傳事件內容後按「驗證事件」。
              </div>
            )
          )}

          <HistoryCard history={history} />
        </div>
      </div>

      {hasReport && (
        <div className={cn("flex-1 min-h-0 overflow-y-auto pr-1", !showReport && "hidden")}>
          <IncidentResponsePanel report={result.report} />
        </div>
      )}

      <ConfirmDialog
        open={confirmOpen && Boolean(preview)}
        title="確認注入事件"
        description={`${summaries.length} 件事件，對齊模擬時間 ${preview?.simulation_clock_time || "-"}`}
        confirmLabel={busy === "inject" ? "注入中…" : "確認注入"}
        cancelLabel="取消"
        confirmDisabled={!readyToInject}
        busy={busy === "inject"}
        tone={preview?.contains_future_event ? "warning" : "default"}
        onConfirm={confirmInject}
        onCancel={cancelInject}
      >
        {preview?.contains_future_event && (
          <Banner
            tone="warning"
            text="內容包含晚於當下模擬時間的事件，注入後會提前套用該時段的路網資料。"
          />
        )}
        <div className="space-y-2">
          {required.map((key) => (
            <label key={key} className="flex items-start gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={confirmed.includes(key)}
                onChange={() => toggleConfirmation(key)}
                disabled={busy === "inject"}
                className="mt-0.5 accent-[var(--primary)] focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              />
              <span className="text-[var(--muted-foreground)]">
                {CONFIRMATION_LABELS[key] || key}
              </span>
            </label>
          ))}
        </div>
      </ConfirmDialog>
    </div>
  );
}

/**
 * 流程列的單一步驟。
 * current＝目前檢視、done＝已完成（顯示打勾）、locked＝條件未達成不可點。
 */
function FlowStep({ index, label, hint, current = false, done = false, locked = false, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={locked}
      aria-current={current ? "step" : undefined}
      title={locked ? "注入完成後才會產出建議書" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs transition",
        "focus-visible:ring-[var(--ring)] focus-visible:ring-[3px] focus-visible:outline-none",
        "disabled:opacity-50 disabled:pointer-events-none",
        current
          ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
          : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50",
        locked && "border-dashed",
      )}
    >
      {done && !current ? (
        <CheckCircle2 className="w-3.5 h-3.5 text-[var(--status-success)] shrink-0" />
      ) : locked ? (
        <Lock className="w-3.5 h-3.5 shrink-0" />
      ) : (
        <span
          className={cn(
            "flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
            current
              ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
              : "bg-[var(--muted)] text-[var(--muted-foreground)]",
          )}
        >
          {index}
        </span>
      )}
      <span className={cn("font-medium", current && "text-[var(--foreground)]")}>{label}</span>
      <span className="text-[10px] text-[var(--muted-foreground)]">{hint}</span>
    </button>
  );
}

function EventSummaryRow({ summary }) {
  const severity = SEVERITY_STYLES[summary.severity] || SEVERITY_STYLES.Medium;
  const SeverityIcon = severity.icon;
  return (
    <div className="rounded-sm border border-[var(--border)] bg-[var(--background)] px-3 py-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-medium">{summary.event_id}</span>
        <span
          className={cn(
            "text-[10px] px-1.5 py-0.5 rounded-sm border font-medium",
            CATEGORY_STYLES[summary.category] || "border-[var(--border)]",
          )}
        >
          {summary.category}
        </span>
        <span
          className={cn(
            "flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-sm font-medium",
            severity.cls,
          )}
        >
          <SeverityIcon className="w-3 h-3" />
          {summary.severity}
        </span>
        <span className="font-mono text-xs text-[var(--muted-foreground)]">
          {summary.affected_segment}
        </span>
      </div>
      <div className="text-xs text-[var(--muted-foreground)] mt-1">
        {summary.location} · {summary.timestamp}
      </div>
      {summary.possible_sop_articles?.length > 0 && (
        <div className="flex items-center gap-1 mt-1.5 flex-wrap">
          <span className="text-[10px] text-[var(--muted-foreground)]">可能觸發</span>
          {summary.possible_sop_articles.map((article) => (
            <span
              key={article}
              className="text-[10px] px-1.5 py-0.5 rounded-sm bg-[var(--status-warning)]/15 text-[var(--status-warning)] font-medium"
            >
              SOP {article}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ErrorCard({ error, keptPreview = false }) {
  return (
    <div className={cn(CARD, "border-[var(--status-error)]/40")}>
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4 text-[var(--status-error)]" />
        <h3 className="text-sm font-semibold text-[var(--status-error)]">{error.message}</h3>
      </div>
      {keptPreview && (
        <p className="text-xs text-[var(--muted-foreground)] mb-2">
          新檔案未通過驗證，已保留下方上一份有效預覽。
        </p>
      )}
      {error.code && (
        <div className="font-mono text-xs text-[var(--muted-foreground)] mb-2">{error.code}</div>
      )}
      {error.details?.length > 0 && (
        <div className="space-y-1">
          {error.details.map((detail, index) => (
            <div
              key={`${detail.path}-${detail.code}-${index}`}
              className="flex items-start gap-2 text-sm"
            >
              <span className="font-mono text-xs text-[var(--status-error)] shrink-0">
                {detail.path}
              </span>
              <span className="text-[var(--muted-foreground)]">{detail.message}</span>
            </div>
          ))}
        </div>
      )}
      {error.traceId && (
        <div className="font-mono text-xs text-[var(--muted-foreground)] mt-2">
          追蹤編號 {error.traceId}
        </div>
      )}
    </div>
  );
}

function ReferenceCard({ catalog, open, onToggle }) {
  return (
    <div className={CARD}>
      <button
        onClick={onToggle}
        className="flex items-center justify-between w-full text-left focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
      >
        <h3 className={SECTION_HEADING}>可引用識別碼</h3>
        {open ? (
          <ArrowUp className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
        ) : (
          <ArrowDown className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
        )}
      </button>

      {open && (
        <div className="space-y-3 mt-3">
          <div>
            <div className="text-xs text-[var(--muted-foreground)] mb-1.5">
              路段（affected_segment / affected_road）
            </div>
            <div className="flex flex-wrap gap-1">
              {(catalog?.segments || []).map((segment) => (
                <span
                  key={segment.segment_id}
                  title={`${segment.name}｜承載容量 ${segment.capacity_vph} 輛/小時`}
                  className="font-mono text-[10px] px-1.5 py-0.5 rounded-sm bg-[var(--muted)] text-[var(--muted-foreground)]"
                >
                  {segment.segment_id}
                </span>
              ))}
            </div>
          </div>

          <div>
            <div className="text-xs text-[var(--muted-foreground)] mb-1.5">
              人流站點（affected_segment）
            </div>
            <div className="flex flex-wrap gap-1">
              {(catalog?.stations || []).map((station) => (
                <span
                  key={station.bs_id}
                  title={station.location_name}
                  className="font-mono text-[10px] px-1.5 py-0.5 rounded-sm bg-[var(--muted)] text-[var(--muted-foreground)]"
                >
                  {station.bs_id}
                </span>
              ))}
            </div>
          </div>

          <div className="text-xs text-[var(--muted-foreground)] space-y-0.5">
            <div>severity：{(catalog?.severities || []).join("、")}</div>
            <div>
              路面事件 status：{(catalog?.road_status_values || []).join("、")}
            </div>
            <div>timestamp：UTC+8 的 YYYY-MM-DD HH:MM</div>
          </div>
        </div>
      )}
    </div>
  );
}

function HistoryCard({ history }) {
  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-2">
        <History className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
        <h3 className={SECTION_HEADING}>近期注入紀錄</h3>
      </div>
      {history.length === 0 ? (
        <div className="text-sm text-[var(--muted-foreground)]">尚無注入紀錄。</div>
      ) : (
        <div className="space-y-2">
          {history.map((item) => (
            <div key={item.injection_id} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[var(--muted-foreground)]">
                  {item.injected_at}
                </span>
                <span className="text-xs text-[var(--muted-foreground)]">
                  模擬時間 {item.simulation_clock_time}
                </span>
              </div>
              <div className="text-[var(--muted-foreground)]">{item.event_ids.join("、")}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Banner({ tone, text }) {
  const tones = {
    error: "bg-[var(--status-error)]/10 text-[var(--status-error)]",
    warning: "bg-[var(--status-warning)]/10 text-[var(--status-warning)]",
  };
  return (
    <div className={cn("flex items-start gap-2 rounded-sm px-3 py-2 text-sm", tones[tone])}>
      <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
      <span>{text}</span>
    </div>
  );
}
