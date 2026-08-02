import { History, Loader2, X } from "lucide-react";
import { cn } from "../lib/utils";

/**
 * 預警紀錄
 *
 * Toast 自動收起後，過往的預警不會消失：每次「異常路段組合或觸發條款」變動
 * 都會留下一筆快照（模擬時間、觸發路段、SOP 條號、AI 摘要），可在這裡回看。
 *
 * 每筆紀錄保存的是偵測當時的數值，點開後看到的就是當下那份判定，
 * 不會被現在的路網狀態覆寫。
 */
export default function AlertHistoryPanel({ history, activeId, onSelect, onClose }) {
  return (
    <div
      // flex-col + min-h-0：清單長度吃剩餘高度並自行捲動，標題列與關閉鈕永遠可見
      className="cc-toast-in flex flex-col min-h-0 bg-[var(--card)]/95 backdrop-blur-sm border border-[var(--border)] rounded-lg shadow-sm overflow-hidden"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-[var(--border)]">
        <History className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
        <h3 className="text-sm font-semibold">預警紀錄</h3>
        <span className="text-xs font-mono text-[var(--muted-foreground)]">
          {history.length}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉預警紀錄"
          className="ml-auto -mr-1 p-1 rounded-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <ul className="flex-1 min-h-0 overflow-y-auto divide-y divide-[var(--border)]">
        {history.map((entry, index) => {
          const sopNumbers = (entry.summary?.sop_triggers || []).map((t) => t.sop_number);
          return (
            <li key={entry.id}>
              <button
                type="button"
                onClick={() => onSelect(entry.id)}
                aria-current={entry.id === activeId ? "true" : undefined}
                className={cn(
                  "w-full text-left px-3 py-2 transition hover:bg-[var(--accent)] focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                  entry.id === activeId && "bg-[var(--accent)]",
                )}
              >
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs font-mono text-[var(--muted-foreground)]">
                    {entry.detectedAt || "—"}
                  </span>
                  {index === 0 && (
                    <span className="px-1.5 rounded-xs bg-[var(--primary)]/15 text-xs text-[var(--primary)] font-medium">
                      最新
                    </span>
                  )}
                  {entry.levelCounts.A > 0 && (
                    <span className="px-1.5 rounded-xs bg-[var(--status-error)]/15 text-xs text-[var(--status-error)] font-medium">
                      A 級 {entry.levelCounts.A}
                    </span>
                  )}
                  {entry.levelCounts.B > 0 && (
                    <span className="px-1.5 rounded-xs bg-[var(--status-warning)]/15 text-xs text-[var(--status-warning)] font-medium">
                      B 級 {entry.levelCounts.B}
                    </span>
                  )}
                  {sopNumbers.length > 0 && (
                    <span className="text-xs text-[var(--muted-foreground)]">
                      SOP 第 {sopNumbers.join("、")} 條
                    </span>
                  )}
                </div>
                {entry.summaryState === "loading" ? (
                  <span className="mt-0.5 flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    產生摘要中...
                  </span>
                ) : (
                  <p className="mt-0.5 text-sm text-[var(--muted-foreground)] line-clamp-2">
                    {entry.summary?.summary || "無摘要（AI 未回應）"}
                  </p>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
