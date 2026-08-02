import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  ChevronDown,
  ChevronUp,
  Eye,
  History,
  Loader2,
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
 * 收合狀態只顯示 AI 摘要（三行內），展開後才列出觸發路段、
 * 同時觸發之 SOP 條款、僅監控路段與條文原文。
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

export default function AlertToast({
  alert,
  autoDismiss = true,
  historyCount = 0,
  isLatest = true,
  onShowHistory,
  onClose,
}) {
  const [expanded, setExpanded] = useState(false);
  // 滑鼠與鍵盤焦點分開記，否則焦點離開時會在游標仍停留其上就恢復計時
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const held = hovered || focused;

  const { detectedAt, triggerSegments, monitoredAlerts, summary, summaryState } = alert;
  const sopTriggers = summary?.sop_triggers || [];
  const sopClauses = summary?.sop_clauses || [];
  const detailCount = triggerSegments.length + sopTriggers.length + monitoredAlerts.length;

  // 換一筆紀錄時回到收合狀態，避免沿用上一筆的展開高度
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
                <p className={cn("text-sm leading-relaxed", !expanded && "line-clamp-3")}>
                  {summary?.summary || "目前沒有可用的摘要。"}
                </p>
              )}
            </div>
            {summary?.source === "fallback" && (
              <p className="mt-1 text-xs text-[var(--status-warning)]">
                AI 未連線，以上為程式判定摘要
              </p>
            )}
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

        {/* 切換列固定排在明細之前：明細再長也不會把它推出可視範圍，
            隨時都能收合（放在明細之後就會發生按不到收合的情況） */}
        {detailCount > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="shrink-0 w-full flex items-center justify-center gap-1 px-3 py-1.5 border-t border-[var(--border)] text-xs font-medium text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            {expanded ? (
              <>
                <ChevronUp className="w-3.5 h-3.5" />
                收合
              </>
            ) : (
              <>
                <ChevronDown className="w-3.5 h-3.5" />
                判定明細
                <span className="font-mono">{detailCount}</span>
              </>
            )}
          </button>
        )}

        {/* 展開後的完整判定內容：高度吃剩餘空間並自行捲動 */}
        {expanded && (
          <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-3 border-t border-[var(--border)]">
            {triggerSegments.length > 0 && (
              <section>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Siren className="w-3.5 h-3.5 text-[var(--status-error)]" />
                  <h4 className="text-xs font-semibold text-[var(--status-error)]">
                    城市應變觸發路段（啟動長綠燈時制）
                  </h4>
                </div>
                <ul className="space-y-1">
                  {triggerSegments.map((s) => (
                    <li
                      key={s.segment_id}
                      className="text-sm bg-[var(--status-error)]/10 px-2.5 py-1.5 rounded-md"
                    >
                      {s.road_name} — {s.level_description}，飽和度{" "}
                      {Math.round(s.saturation_score * 100)}%，時速 {s.avg_speed} 公里
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {sopTriggers.length > 0 && (
              <section>
                <h4 className="text-xs font-semibold text-[var(--status-warning)] mb-1.5">
                  同時觸發之 SOP 條款
                </h4>
                <ul className="space-y-1.5">
                  {sopTriggers.map((t) => (
                    <li
                      key={t.sop_number}
                      className="text-sm bg-[var(--status-warning)]/10 px-2.5 py-1.5 rounded-md"
                    >
                      <span className="font-medium">
                        SOP 第 {t.sop_number} 條 {t.sop_title}
                      </span>
                      <div className="text-xs text-[var(--muted-foreground)] mt-0.5">
                        {t.reason}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {monitoredAlerts.length > 0 && (
              <section>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Eye className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
                  <h4 className="text-xs font-semibold text-[var(--muted-foreground)]">
                    其他達級別路段（依 SOP 第 1 條僅供燈號顯示，不啟動應變）
                  </h4>
                </div>
                <p className="text-sm text-[var(--muted-foreground)]">
                  {monitoredAlerts.map((m) => `${m.road_name} ${m.level_description}`).join("、")}
                </p>
              </section>
            )}

            {sopClauses.length > 0 && (
              <details>
                <summary className="text-xs font-semibold text-[var(--muted-foreground)] cursor-pointer flex items-center gap-1.5">
                  <ShieldAlert className="w-3.5 h-3.5" />
                  判定依據的 SOP 條文原文（{sopClauses.length} 條）
                </summary>
                <div className="mt-2 space-y-2">
                  {sopClauses.map((c) => (
                    <pre
                      key={c.sop_number}
                      className="font-mono text-xs whitespace-pre-wrap bg-[var(--muted)] p-2.5 rounded-md text-[var(--muted-foreground)]"
                    >
                      {c.text}
                    </pre>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
