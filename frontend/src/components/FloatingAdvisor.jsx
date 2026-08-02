import { useEffect, useRef, useState } from "react";
import { Bot } from "lucide-react";
import { cn } from "../lib/utils";
import AdvisorChat from "./AdvisorChat";

/**
 * AI 策略顧問浮動聊天室
 *
 * 顧問從獨立分頁改成釘在畫面右下角：指揮官不必離開儀表板或監控頁就能問
 * What-if，符合「Contextual, not modal」——沒有遮罩、不搶焦點，
 * 底下的地圖與表格仍可操作。
 *
 * 收起時只留一顆啟動鈕，並以徽章顯示未讀的顧問回覆（在關閉期間新增的訊息），
 * 讓長時間運算的回覆不會被漏看。展開狀態分「一般」與「放大」兩段尺寸。
 */
export default function FloatingAdvisor(props) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [unread, setUnread] = useState(0);
  const inputRef = useRef(null);
  const launcherRef = useRef(null);
  const panelRef = useRef(null);

  const { messages } = props;
  const seenCountRef = useRef(messages.length);

  // 關閉期間新增的顧問回覆記為未讀；開啟時歸零並把游標交給輸入框
  useEffect(() => {
    if (open) {
      seenCountRef.current = messages.length;
      setUnread(0);
      return;
    }
    const added = messages.length - seenCountRef.current;
    if (added > 0) setUnread(added);
    else if (added < 0) seenCountRef.current = messages.length; // 重設對話
  }, [messages, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const close = () => {
    setOpen(false);
    launcherRef.current?.focus();
  };

  if (!open) {
    return (
      <button
        ref={launcherRef}
        type="button"
        onClick={() => setOpen(true)}
        aria-label="開啟 AI 策略顧問"
        aria-expanded={false}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-[var(--primary)] px-4 py-3 text-sm font-medium text-[var(--primary-foreground)] shadow-sm transition hover:opacity-90 focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
      >
        <Bot className="w-4 h-4" />
        AI 策略顧問
        {unread > 0 && (
          <span className="ml-0.5 rounded-full bg-[var(--card)] px-1.5 text-[10px] font-bold text-[var(--primary)]">
            {unread}
          </span>
        )}
      </button>
    );
  }

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="AI 策略顧問"
      onKeyDown={(e) => {
        // 只監聽面板內的按鍵，不掛全域監聽，避免搶走其他元件的 Escape
        if (e.key === "Escape") close();
      }}
      className={cn(
        "cc-panel-in fixed bottom-5 right-5 z-40 flex flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-sm",
        expanded
          ? "w-[min(46rem,calc(100vw-2.5rem))] h-[min(46rem,calc(100vh-6rem))]"
          : "w-[min(26rem,calc(100vw-2.5rem))] h-[min(34rem,calc(100vh-6rem))]",
      )}
    >
      <AdvisorChat
        {...props}
        onClose={close}
        expanded={expanded}
        onToggleExpanded={() => setExpanded((v) => !v)}
        inputRef={inputRef}
      />
    </div>
  );
}
