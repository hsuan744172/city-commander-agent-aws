import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  ChevronRight,
  Eye,
  History,
  Loader2,
  ScanSearch,
  ShieldAlert,
  Siren,
  X,
} from "lucide-react";
import { cn } from "../lib/utils";

/**
 * 路網異常自動預警 — Toast
 *
 * 取代原本的置中彈窗：疊在地圖左上角，不遮蔽畫面、不搶焦點、
 * 不阻擋地圖操作，指揮官可以邊看地圖邊讀預警
 * （對應設計原則 Contextual, not modal）。
 *
 * 收合狀態只顯示 AI 摘要（三行內），展開後才列出「這段研判的依據數據」：
 * 餵給語言模型的既算好事實（分級門檻、A/B 級路段清單、觸發條款與理由、
 * 僅監控路段），最後再巢狀收合條文原文。指揮官因此能逐項核對摘要裡的
 * 每個數字都來自程式判定，而非模型自行編造。
 *
 * 只負責呈現一筆預警紀錄（alert entry），資料快照與歷史清單由
 * AlertCenter 管理，因此回看舊紀錄時顯示的是當時的數值，不會被
 * 現在的路網狀態覆寫。
 *
 * 自動收起：僅在 autoDismiss 為真（剛偵測到的最新一筆）時計時，
 * 滑鼠移入、鍵盤聚焦或展開時暫停，避免讀到一半被抽走。
 * 從歷史紀錄開啟的不自動收起。
 */
const AUTO_DISMISS_MS = 12000;

/**
 * 判定依據區最上方的固定說明。
 *
 * 預警 toast、預警紀錄與路段研判三處共用同一句，措辭只有一份，不會各自漂移。
 */
export const AI_EVIDENCE_NOTE =
  "以下數值均由程式依標準程序運算後才交給語言模型撰寫敘述；語言模型不參與門檻判定，也不會新增數值。";

/** 收合標題也共用一份，兩處的入口文字一致，使用者不必猜是不是同一種東西。 */
export const AI_EVIDENCE_TITLE = "這段研判的依據數據";

/** Bedrock 不可用（source 為 fallback）時的統一措辭，同樣三處共用。 */
export const AI_FALLBACK_NOTE = "AI 未連線，以下為程式依判定結果直述";

/** 飽和度一律以整數百分比呈現，與地圖、趨勢圖、報告同一種寫法。 */
export function saturationPct(score) {
  return `${Math.round(Number(score || 0) * 100)}%`;
}

/**
 * 判定依據的收合殼層（原生 details）
 *
 * 用 <details> 而不是自管 state 的按鈕：收合時只佔一行標題高度，
 * 展開語意與鍵盤操作由瀏覽器負責，不必自己維護 aria-expanded。
 * 固定說明由這層統一渲染，呼叫端只提供數值內容。
 */
export function EvidenceDisclosure({
  title = AI_EVIDENCE_TITLE,
  count = null,
  children,
  className = "",
  summaryClassName = "",
  onToggle = undefined,
}) {
  return (
    <details className={cn("group", className)} onToggle={onToggle}>
      <summary
        className={cn(
          "flex cursor-pointer list-none flex-wrap items-center gap-1.5 text-xs font-medium text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]",
          summaryClassName,
        )}
      >
        <ChevronRight className="w-3.5 h-3.5 shrink-0 transition-transform group-open:rotate-90" />
        <ScanSearch className="w-3.5 h-3.5 shrink-0 text-[var(--status-info)]" />
        <span className="text-[var(--status-info)]">{title}</span>
        {count > 0 && <span className="text-xs tabular-nums">{count} 項</span>}
        <span className="text-xs group-open:hidden">（點擊展開）</span>
      </summary>
      <div className="mt-2 space-y-2 border-l-2 border-[var(--status-info)]/30 pl-2.5">
        <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
          {AI_EVIDENCE_NOTE}
        </p>
        {children}
      </div>
    </details>
  );
}

/** 依據區的一個小節。標題不用 heading 標籤，避免在不同宿主卡片裡打亂層級。 */
export function EvidenceSection({ title, children }) {
  return (
    <section>
      <div className="mb-1 text-xs font-semibold">{title}</div>
      {children}
    </section>
  );
}

/** 「標籤 數值」的一列：數值用 tabular-nums 對齊，但不套等寬字體。 */
export function EvidenceRow({ label, value, note = null }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
      <span className="text-[var(--muted-foreground)]">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
      {note && <span className="text-[var(--muted-foreground)]">{note}</span>}
    </div>
  );
}

/**
 * 巢狀的條文原文收合區
 *
 * 依據區本身已經是收合的，條文原文再收一層：核對數值時不需要條文全文，
 * 要查的人才展開。法規原文照抄不改排版，所以這裡（也只有這裡）用等寬字。
 */
export function SopClauseDisclosure({ clauses }) {
  if (!clauses?.length) return null;

  return (
    <details className="group/clause">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]">
        <ChevronRight className="w-3 h-3 shrink-0 transition-transform group-open/clause:rotate-90" />
        <ShieldAlert className="w-3 h-3 shrink-0" />
        引用條文原文（{clauses.length} 條）
      </summary>
      <div className="mt-1.5 space-y-1.5">
        {clauses.map((c) => (
          <div key={c.sop_number}>
            <div className="text-xs font-medium">
              SOP 第 {c.sop_number} 條 {c.title}
            </div>
            <pre className="mt-0.5 whitespace-pre-wrap rounded-md bg-[var(--muted)] p-2 font-mono text-xs leading-relaxed text-[var(--muted-foreground)]">
              {c.text}
            </pre>
          </div>
        ))}
      </div>
    </details>
  );
}

/** A/B 級路段清單的一列，標注是否為 SOP 第 1 條的城市應變觸發路段。 */
function SegmentEvidenceList({ items }) {
  return (
    <ul className="space-y-1">
      {items.map((s) => (
        <li
          key={s.segment_id}
          className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-xs"
        >
          <span className="font-medium">{s.road_name}</span>
          <span className="text-[var(--muted-foreground)]">飽和度</span>
          <span className="font-medium tabular-nums">
            {saturationPct(s.saturation_score)}
          </span>
          <span className="text-[var(--muted-foreground)]">時速</span>
          <span className="font-medium tabular-nums">{s.avg_speed} 公里</span>
          {s.is_trigger_segment ? (
            <span className="inline-flex items-center gap-1 rounded-xs bg-[var(--status-error)]/15 px-1.5 font-medium text-[var(--status-error)]">
              <Siren className="w-3 h-3" />
              城市應變觸發路段
            </span>
          ) : (
            <span className="rounded-xs bg-[var(--muted)] px-1.5 text-[var(--muted-foreground)]">
              非觸發路段
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function AlertToast({
  alert,
  autoDismiss = true,
  historyCount = 0,
  isLatest = true,
  onShowHistory,
  onClose,
}) {
  // 滑鼠與鍵盤焦點分開記，否則焦點離開時會在游標仍停留其上就恢復計時
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const held = hovered || focused;

  const {
    detectedAt,
    triggerSegments,
    monitoredAlerts,
    thresholds,
    summary,
    summaryState,
  } = alert;
  const sopTriggers = summary?.sop_triggers || [];
  const sopClauses = summary?.sop_clauses || [];

  // 依據優先取摘要負載裡的完整 A/B 級清單（那正是餵給模型的那份事實）；
  // 摘要還在產生或取得失敗時，退回偵測當時的觸發路段快照，展開後不會空白。
  const levelA = summary?.level_a || null;
  const levelB = summary?.level_b || null;
  const hasSummaryLists = Array.isArray(levelA) || Array.isArray(levelB);
  const levelAThreshold = thresholds?.level_a ?? 0.95;
  const levelBThreshold = thresholds?.level_b ?? 0.85;

  const evidenceCount = hasSummaryLists
    ? (levelA?.length || 0) + (levelB?.length || 0) + sopTriggers.length
    : triggerSegments.length + sopTriggers.length + monitoredAlerts.length;
  const hasEvidence =
    evidenceCount > 0 || monitoredAlerts.length > 0 || sopClauses.length > 0;

  // details 的開合狀態鏡射到 state，僅供「暫停自動收起」與摘要不截行使用。
  // 換一筆紀錄時 details 會連同 key 重新掛載回收合，這裡同步歸零。
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    setExpanded(false);
  }, [alert.id]);

  // 自動收起計時器：展開、滑入或聚焦時暫停
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!autoDismiss || expanded || held) return;
    const timer = setTimeout(() => closeRef.current(), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [autoDismiss, expanded, held]);

  return (
    <div
      // 高度鏈：AlertCenter 給上限 → 這層傳遞 → 卡片內的明細區塊自行捲動
      className="flex flex-col min-h-0"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      // 只有鍵盤操作（focus-visible）才暫停自動收起。若連滑鼠點擊留下的焦點
      // 也算，展開／收合按一下之後焦點留在 toast 內，計時器就永遠不會恢復，
      // toast 會變成關不掉的常駐視窗。
      onFocus={(e) => setFocused(e.target.matches?.(":focus-visible") ?? false)}
      onBlur={() => setFocused(false)}
      onKeyDown={(e) => {
        // 僅在焦點位於 toast 內時生效，不掛全域監聽以免影響其他元件
        if (e.key === "Escape") onClose();
      }}
    >
      <div
        role="status"
        aria-live="polite"
        aria-label="路網異常自動預警"
        // flex-col + min-h-0：高度上限由外層容器給，超長的明細在自己的區塊
        // 內捲動，不會把卡片撐出可視範圍（外層是 overflow-hidden，撐出去就再也點不到）
        className="cc-toast-in flex flex-col min-h-0 bg-[var(--card)]/95 backdrop-blur-sm border border-[var(--status-error)]/40 border-l-2 border-l-[var(--status-error)] rounded-lg shadow-sm overflow-hidden"
      >
        <div className="shrink-0 flex items-start gap-2 px-3 py-2.5">
          <AlertTriangle className="w-4 h-4 text-[var(--status-error)] shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-[var(--status-error)]">
                路網異常自動預警
              </h3>
              {!isLatest && (
                <span className="px-1.5 rounded-xs bg-[var(--muted)] text-xs text-[var(--muted-foreground)]">
                  歷史紀錄
                </span>
              )}
              {detectedAt && (
                <span className="ml-auto text-xs font-mono text-[var(--muted-foreground)]">
                  {detectedAt}
                </span>
              )}
            </div>

            {/* LLM 生成的摘要；收合時最多三行 */}
            <div className="mt-1.5 flex items-start gap-1.5">
              <Bot className="w-3.5 h-3.5 text-[var(--primary)] shrink-0 mt-0.5" />
              {summaryState === "loading" ? (
                <span className="flex items-center gap-1.5 text-sm text-[var(--muted-foreground)]">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  產生摘要中...
                </span>
              ) : (
                <div className="min-w-0 flex-1">
                  {/* 標示排在摘要之前，「以下」才指得到那段文字 */}
                  {summary?.source === "fallback" && (
                    <p className="mb-0.5 text-xs text-[var(--status-warning)]">
                      {AI_FALLBACK_NOTE}
                    </p>
                  )}
                  <p className={cn("text-sm leading-relaxed", !expanded && "line-clamp-3")}>
                    {summary?.summary || "目前沒有可用的摘要。"}
                  </p>
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-0.5 -mr-1 -mt-0.5 shrink-0">
            {historyCount > 0 && (
              <button
                type="button"
                onClick={onShowHistory}
                aria-label={`查看預警紀錄，共 ${historyCount} 筆`}
                title="預警紀錄"
                className="flex items-center gap-1 p-1 rounded-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <History className="w-3.5 h-3.5" />
                <span className="text-xs font-mono">{historyCount}</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="關閉預警"
              className="p-1 rounded-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* 判定依據：原生 details，收合時只佔一行標題高度，不影響 toast 的預設尺寸。
            外層負責捲動（內容再長也不會把 toast 撐出可視範圍），標題列 sticky
            釘在捲動區頂端，展開後仍隨時可以收回去。 */}
        {hasEvidence && (
          <div
            // key：換一筆紀錄時 details 重新掛載回收合狀態，
            // 不會沿用上一筆的展開高度（expanded state 也同步歸零）
            key={alert.id}
            className="flex-1 min-h-0 overflow-y-auto border-t border-[var(--border)] px-3 py-2"
          >
            <EvidenceDisclosure
              count={evidenceCount}
              summaryClassName="sticky top-0 z-10 -mx-3 -mt-2 bg-[var(--card)]/95 px-3 py-2 backdrop-blur-sm"
              onToggle={(e) => setExpanded(e.currentTarget.open)}
            >
              <EvidenceSection title="判定門檻（SOP 第 1 條）">
                <EvidenceRow
                  label="A 級癱瘓"
                  value={`飽和度 ≥ ${saturationPct(levelAThreshold)}`}
                />
                <EvidenceRow
                  label="B 級壅擠"
                  value={`飽和度 ≥ ${saturationPct(levelBThreshold)}`}
                />
              </EvidenceSection>

              {hasSummaryLists ? (
                <>
                  {levelA?.length > 0 && (
                    <EvidenceSection title={`A 級癱瘓路段（${levelA.length} 條）`}>
                      <SegmentEvidenceList items={levelA} />
                    </EvidenceSection>
                  )}
                  {levelB?.length > 0 && (
                    <EvidenceSection title={`B 級壅擠路段（${levelB.length} 條）`}>
                      <SegmentEvidenceList items={levelB} />
                    </EvidenceSection>
                  )}
                </>
              ) : (
                triggerSegments.length > 0 && (
                  <EvidenceSection title="城市應變觸發路段（偵測當時快照）">
                    <SegmentEvidenceList items={triggerSegments} />
                  </EvidenceSection>
                )
              )}

              {sopTriggers.length > 0 && (
                <EvidenceSection title="已觸發的 SOP 條款">
                  <ul className="space-y-1.5">
                    {sopTriggers.map((t) => (
                      <li key={t.sop_number} className="text-xs">
                        <span className="font-medium">
                          SOP 第 {t.sop_number} 條 {t.sop_title}
                        </span>
                        <p className="mt-0.5 leading-relaxed text-[var(--muted-foreground)]">
                          觸發理由：{t.reason}
                        </p>
                      </li>
                    ))}
                  </ul>
                </EvidenceSection>
              )}

              {monitoredAlerts.length > 0 && (
                <EvidenceSection title="其他達級別路段（依 SOP 第 1 條僅供燈號顯示，不啟動應變）">
                  <p className="flex items-start gap-1.5 text-xs text-[var(--muted-foreground)]">
                    <Eye className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    <span>
                      {monitoredAlerts
                        .map((m) => `${m.road_name} ${m.level_description}`)
                        .join("、")}
                    </span>
                  </p>
                </EvidenceSection>
              )}

              <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                僅城市應變觸發路段達級別才啟動長綠燈時制，其餘路段依 SOP 第 1 條僅作燈號顯示。
              </p>

              <SopClauseDisclosure clauses={sopClauses} />
            </EvidenceDisclosure>
          </div>
        )}
      </div>
    </div>
  );
}
