import { Brain, Database, Sparkles, Wrench } from "lucide-react";
import { cn } from "../lib/utils";
import { toolLabel } from "../lib/aiLabels";

/**
 * AI 思考過程（Chain-of-Thought）軌跡
 *
 * 命題模組 4 要求「在 Dashboard 上清楚展示 AI 的推理過程」。後端在呼叫 Bedrock 時
 * 開啟 extended thinking，把模型回傳的 reasoningContent 與工具往返按順序記錄下來
 * （backend/agents/architect.py::_reasoning_from），這裡就是那份紀錄的呈現。
 *
 * 為什麼是「記錄」而不是「請模型自述推理」：後者只會得到事後編排的說明文字，
 * 與模型實際的判斷過程無關，也無法證明它真的查過確定性工具。
 *
 * 建議書與 What-if 對話共用這個元件，兩處的呈現方式一致。
 */
export default function AiReasoningTrace({
  reasoning,
  defaultOpen = false,
  compact = false,
}) {
  if (!reasoning) return null;

  const steps = reasoning.steps || [];
  const hasContent = steps.length > 0 || Boolean(reasoning.thinking_text);

  // 完全沒有軌跡時只留一行說明，不佔畫面
  if (!hasContent) {
    return (
      <p className="text-xs text-[var(--muted-foreground)]">
        {reasoning.note || "本輪未記錄到 AI 思考軌跡。"}
      </p>
    );
  }

  const thinkingCount = reasoning.thinking_block_count || 0;
  const toolCount = reasoning.tool_call_count || 0;

  return (
    <details open={defaultOpen} className="group">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 text-xs text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]">
        <Brain className="h-3.5 w-3.5 text-[var(--status-info)]" />
        <span className="font-medium text-[var(--status-info)]">AI 思考過程</span>
        <span className="text-[10px]">
          {thinkingCount > 0 && `${thinkingCount} 段推理`}
          {thinkingCount > 0 && toolCount > 0 && "、"}
          {toolCount > 0 && `${toolCount} 次工具核對`}
        </span>
        <span className="text-[10px] group-open:hidden">（點擊展開）</span>
      </summary>

      <div className={cn("mt-2 space-y-1.5", compact && "text-xs")}>
        {reasoning.thinking_enabled === false && (
          <p className="rounded-sm bg-[var(--muted)] px-2.5 py-1.5 text-[10px] text-[var(--muted-foreground)]">
            本次部署未啟用 extended thinking，以下僅為工具呼叫軌跡。
          </p>
        )}

        <ol className="space-y-1.5">
          {steps.map((step) => (
            <li key={step.order}>
              <TraceStep step={step} />
            </li>
          ))}
        </ol>

        {reasoning.note && (
          <p className="text-[10px] text-[var(--muted-foreground)]">{reasoning.note}</p>
        )}
      </div>
    </details>
  );
}

function TraceStep({ step }) {
  if (step.kind === "thinking") {
    return (
      <div className="flex gap-2 rounded-md border-l-2 border-[var(--status-info)]/50 bg-[var(--status-info)]/5 py-1.5 pl-2.5 pr-2">
        <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-[var(--status-info)]" />
        <div className="min-w-0">
          <div className="text-[10px] font-medium text-[var(--status-info)]">
            {step.order}. 模型思考
          </div>
          <p className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed text-[var(--foreground)]">
            {step.text}
          </p>
        </div>
      </div>
    );
  }

  if (step.kind === "tool_use") {
    const args = Object.entries(step.input || {}).filter(
      ([, value]) => value !== null && value !== undefined && value !== "",
    );
    return (
      <div className="flex gap-2 rounded-md bg-[var(--muted)] py-1.5 pl-2.5 pr-2">
        <Wrench className="mt-0.5 h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
        <div className="min-w-0">
          <div className="text-[10px] font-medium text-[var(--muted-foreground)]">
            {step.order}. 呼叫確定性工具
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">
            <span className="font-medium">{toolLabel(step.tool)}</span>
            <span className="font-mono text-[10px] text-[var(--muted-foreground)]">
              {step.tool}
            </span>
          </div>
          {args.length > 0 && (
            <div className="mt-0.5 font-mono text-[10px] text-[var(--muted-foreground)]">
              {args.map(([key, value]) => `${key}=${value}`).join("  ")}
            </div>
          )}
        </div>
      </div>
    );
  }

  const failed = step.status === "error";
  return (
    <div
      className={cn(
        "flex gap-2 rounded-md py-1.5 pl-2.5 pr-2",
        failed ? "bg-[var(--status-error)]/10" : "bg-[var(--background)]",
      )}
    >
      <Database
        className={cn(
          "mt-0.5 h-3 w-3 shrink-0",
          failed ? "text-[var(--status-error)]" : "text-[var(--status-success)]",
        )}
      />
      <div className="min-w-0">
        <div
          className={cn(
            "text-[10px] font-medium",
            failed ? "text-[var(--status-error)]" : "text-[var(--muted-foreground)]",
          )}
        >
          {step.order}. 工具回傳{failed ? "錯誤" : "結果"}
          {step.tool && (
            <span className="ml-1 font-mono opacity-70">{step.tool}</span>
          )}
        </div>
        <p className="mt-0.5 break-all font-mono text-[10px] leading-relaxed text-[var(--muted-foreground)]">
          {step.summary || "（無內容）"}
        </p>
      </div>
    </div>
  );
}
