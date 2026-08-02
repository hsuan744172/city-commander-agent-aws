import { useEffect, useId, useRef } from "react";
import { AlertTriangle, HelpCircle, Loader2 } from "lucide-react";
import { cn } from "../lib/utils";

/** 焦點鎖定的取樣範圍：只挑真正能收到鍵盤焦點的元素。 */
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

const TONES = {
  default: {
    icon: HelpCircle,
    iconCls: "text-[var(--primary)]",
    confirmCls: "bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90",
  },
  warning: {
    icon: AlertTriangle,
    iconCls: "text-[var(--status-warning)]",
    confirmCls: "bg-[var(--status-warning)] text-[var(--primary-foreground)] hover:opacity-90",
  },
  danger: {
    icon: AlertTriangle,
    iconCls: "text-[var(--status-error)]",
    confirmCls: "bg-[var(--status-error)] text-[var(--primary-foreground)] hover:opacity-90",
  },
};

/**
 * 通用確認對話框
 *
 * 用於「執行前要停下來看一眼」的破壞性或不可逆動作：遮住底層畫面、把焦點收進卡片內，
 * 讓確認這件事無法被順手滑過去。不依賴任何對話框套件，配色與圓角沿用專案的設計 token。
 *
 * 無障礙行為：role="dialog" + aria-modal、標題以 aria-labelledby 綁定、開啟時把焦點移入
 * 對話框並在關閉後還原到觸發元件、Esc 與點擊背景可關閉、Tab/Shift+Tab 在卡片內循環。
 * busy 為 true 時視為動作進行中：確認鈕顯示忙碌狀態，且 Esc／背景／取消都不會中斷。
 */
export default function ConfirmDialog({
  open,
  title,
  description = "",
  confirmLabel = "確認",
  cancelLabel = "取消",
  confirmDisabled = false,
  busy = false,
  tone = "default",
  onConfirm,
  onCancel,
  children,
}) {
  const dialogRef = useRef(null);
  const titleId = useId();
  const descriptionId = useId();

  // 開啟時把焦點移進對話框，關閉時還原給觸發元件（通常是那顆按鈕）
  useEffect(() => {
    if (!open) return undefined;
    const trigger = document.activeElement;
    dialogRef.current?.focus();
    return () => {
      if (trigger instanceof HTMLElement && document.body.contains(trigger)) trigger.focus();
    };
  }, [open]);

  // 背後的長列表不該還能滾動，否則使用者會以為畫面沒被鎖住
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;

  const dismiss = () => {
    if (busy) return;
    onCancel?.();
  };

  const handleKeyDown = (event) => {
    if (event.key === "Escape") {
      // 只處理自己的 Escape，不掛全域監聽，避免搶走其他面板的關閉鍵
      event.stopPropagation();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;

    const nodes = Array.from(dialogRef.current?.querySelectorAll(FOCUSABLE) || []).filter(
      (node) => node.offsetParent !== null,
    );
    if (nodes.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }

    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialogRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || active === dialogRef.current)) {
      event.preventDefault();
      first.focus();
    }
  };

  const toneStyle = TONES[tone] || TONES.default;
  const ToneIcon = toneStyle.icon;

  return (
    <div
      // 蓋在浮動顧問（z-40）之上；只有點在遮罩本身才關閉，點卡片內不會誤觸
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) dismiss();
      }}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          // 沿用既有的進場動畫（已尊重「減少動態效果」偏好），中心縮放不需要額外 origin
          "cc-toast-in flex flex-col w-[min(30rem,100%)] max-h-[calc(100vh-4rem)]",
          "rounded-lg border border-[var(--border)] bg-[var(--card)] shadow-lg",
          "focus-visible:outline-none",
        )}
      >
        <div className="shrink-0 flex items-start gap-2.5 px-4 pt-4">
          <ToneIcon className={cn("w-4 h-4 mt-0.5 shrink-0", toneStyle.iconCls)} />
          <div className="min-w-0 space-y-1">
            <h2 id={titleId} className="text-sm font-semibold text-[var(--foreground)]">
              {title}
            </h2>
            {description && (
              <p id={descriptionId} className="text-xs text-[var(--muted-foreground)]">
                {description}
              </p>
            )}
          </div>
        </div>

        {children && (
          <div className="min-h-0 overflow-y-auto px-4 pt-3 space-y-2.5">{children}</div>
        )}

        <div className="shrink-0 flex items-center justify-end gap-2 px-4 py-4">
          <button
            type="button"
            onClick={dismiss}
            disabled={busy}
            className="px-3 py-1.5 rounded-md text-xs font-medium border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50 transition disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={() => {
              if (busy || confirmDisabled) return;
              onConfirm?.();
            }}
            disabled={busy || confirmDisabled}
            aria-busy={busy || undefined}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition",
              "disabled:opacity-50 disabled:pointer-events-none",
              "focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
              toneStyle.confirmCls,
            )}
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
