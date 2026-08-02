import { useState } from "react";
import { History } from "lucide-react";
import AlertToast from "./AlertToast";
import AlertHistoryPanel from "./AlertHistoryPanel";

/**
 * 預警中心
 *
 * 疊在地圖左上角，只會同時出現一種狀態：
 *   1. 預警 toast — 剛偵測到的異常，靜置後自動收起
 *   2. 預警紀錄清單 — 回看過往預警
 *   3. 收合的紀錄按鈕 — toast 收起後留下的入口，不佔畫面
 *
 * 用 absolute 而非 fixed，寬螢幕時才會跟著內容區對齊而不是飄到留白上。
 * 地圖自身的圖例在左下、縮放控制在右上，不會互相遮蔽。
 */
export default function AlertCenter({ history, activeId, onSelect }) {
  const [listOpen, setListOpen] = useState(false);
  // 從紀錄清單手動打開的不自動收起（使用者是刻意要看的）
  const [pinnedId, setPinnedId] = useState(null);

  if (history.length === 0) return null;

  const activeEntry = history.find((entry) => entry.id === activeId) || null;
  const latestId = history[0].id;
  const hasCritical = history[0].levelCounts.A > 0;

  const selectFromHistory = (id) => {
    setPinnedId(id);
    setListOpen(false);
    onSelect(id);
  };

  return (
    // max-h + flex-col：內容再長也不超過儀表板可視高度，超出的部分由
    // toast／紀錄清單自己捲動，不會被外層的 overflow-hidden 裁掉而點不到
    <div className="absolute top-4 left-4 z-30 flex flex-col w-[380px] max-w-[calc(100%-2rem)] max-h-[calc(100%-2rem)]">
      {listOpen ? (
        <AlertHistoryPanel
          history={history}
          activeId={activeId}
          onSelect={selectFromHistory}
          onClose={() => setListOpen(false)}
        />
      ) : activeEntry ? (
        <AlertToast
          alert={activeEntry}
          autoDismiss={activeEntry.id !== pinnedId}
          historyCount={history.length}
          isLatest={activeEntry.id === latestId}
          onShowHistory={() => setListOpen(true)}
          onClose={() => onSelect(null)}
        />
      ) : (
        <button
          type="button"
          onClick={() => setListOpen(true)}
          // self-start + inline-flex：只佔文字寬度，不會撐成 380px 的長條
          className="cc-toast-in self-start inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-[var(--border)] bg-[var(--card)]/95 backdrop-blur-sm shadow-sm text-xs font-medium text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
        >
          <History className="w-3.5 h-3.5" />
          預警紀錄
          <span
            className={
              hasCritical
                ? "px-1.5 rounded-full bg-[var(--status-error)] text-[var(--primary-foreground)] font-mono"
                : "px-1.5 rounded-full bg-[var(--muted)] font-mono"
            }
          >
            {history.length}
          </span>
        </button>
      )}
    </div>
  );
}
