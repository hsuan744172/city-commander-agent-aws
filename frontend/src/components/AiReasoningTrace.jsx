import { Brain, ChevronRight, Database, FileSearch, Sparkles } from "lucide-react";
import { cn } from "../lib/utils";
import { summarizeToolResult, toolNarrative } from "../lib/explain";

/**
 * AI 推理過程
 *
 * 命題模組 4 要求「在 Dashboard 上清楚展示 AI 的推理過程」。後端呼叫 Bedrock 時
 * 開啟 extended thinking，把模型的 reasoningContent 與工具往返依序記錄下來
 * （backend/agents/architect.py::_reasoning_from），這裡是那份紀錄的呈現。
 *
 * 為什麼是「記錄」而不是「請模型自述推理」：後者只會得到事後編排的說明文字，
 * 與模型實際的判斷過程無關，也無法證明它真的查過確定性工具。
 *
 * 呈現採兩層漸進揭露：
 *   第一層  一句話講完 AI 做了什麼（常駐在 summary 上）
 *   第二層  逐步軌跡，工具呼叫寫成「查了什麼 → 得到什麼」，
 *           模型思考文字節錄；完整原文再巢狀收合一層標示「供稽核」
 *
 * 原本的版本把工具代號與整段回傳字串以等寬字 break-all 直接倒出來，
 * 資訊量大但沒人讀得下去，也看不出哪裡可以驗證。
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
        {reasoning.note || "本輪未記錄到 AI 推理軌跡。"}
      </p>
    );
  }

  const thinkingCount = reasoning.thinking_block_count || 0;
  const toolCount = reasoning.tool_call_count || 0;

  // 第一層：一句話講完 AI 在這一輪做了什麼，不必展開就能判斷值不值得細看
  const headline = [
    thinkingCount > 0 ? `${thinkingCount} 段推理` : "",
    toolCount > 0 ? `核對 ${toolCount} 次確定性數據` : "",
  ]
    .filter(Boolean)
    .join("、");

  return (
    <details open={defaultOpen} className="group">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 text-xs text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]">
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" />
        <Brain className="h-3.5 w-3.5 shrink-0 text-[var(--status-info)]" />
        <span className="font-medium text-[var(--status-info)]">AI 推理過程</span>
        {headline && <span>{headline}</span>}
        <span className="group-open:hidden">（點擊展開）</span>
      </summary>

      <div className={cn("mt-2 space-y-2", compact && "text-xs")}>
        {reasoning.thinking_enabled === false && (
          <p className="rounded-sm bg-[var(--muted)] px-2.5 py-1.5 text-xs text-[var(--muted-foreground)]">
            本次部署未啟用模型思考記錄，以下僅為工具核對軌跡。
          </p>
        )}

        <ol className="space-y-1.5 border-l-2 border-[var(--status-info)]/30 pl-2.5">
          {steps.map((step) => (
            <li key={step.order}>
              <TraceStep step={step} />
            </li>
          ))}
        </ol>

        {reasoning.note && (
          <p className="text-xs text-[var(--muted-foreground)]">{reasoning.note}</p>
        )}
      </div>
    </details>
  );
}

function TraceStep({ step }) {
  if (step.kind === "thinking") {
    const text = String(step.text || "");
    // 思考文字動輒數百字，先給前段讓人抓到重點，全文收在下一層
    const excerpt = text.length > 220 ? `${text.slice(0, 220).trimEnd()}…` : text;

    return (
      <div className="rounded-md bg-[var(--status-info)]/5 px-2.5 py-1.5">
        <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--status-info)]">
          <Sparkles className="h-3 w-3 shrink-0" />
          {step.order}. 模型思考
        </div>
        <p className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed">{excerpt}</p>
        {text.length > excerpt.length && (
          <details className="mt-1">
            <summary className="cursor-pointer list-none text-xs text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]">
              顯示這段推理的完整原文（供稽核）
            </summary>
            <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-[var(--muted-foreground)]">
              {text}
            </p>
          </details>
        )}
      </div>
    );
  }

  if (step.kind === "tool_use") {
    // 「查了什麼」：動作用人看得懂的名稱，參數以「鍵 值」呈現而非 JSON
    const { action, asked } = toolNarrative(step);
    return (
      <div className="rounded-md bg-[var(--muted)] px-2.5 py-1.5">
        <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--muted-foreground)]">
          <FileSearch className="h-3 w-3 shrink-0" />
          {step.order}. 查詢確定性數據
        </div>
        <p className="mt-0.5 text-xs leading-relaxed">
          <span className="font-medium">{action}</span>
          {asked && (
            <span className="text-[var(--muted-foreground)]">，查詢條件：{asked}</span>
          )}
        </p>
      </div>
    );
  }

  // 工具回傳：「得到什麼」。摘要為單行可讀文字，原始內容收進下一層
  const failed = step.status === "error";
  const raw = String(step.summary || "");
  const brief = summarizeToolResult(raw);

  return (
    <div
      className={cn(
        "rounded-md px-2.5 py-1.5",
        failed ? "bg-[var(--status-error)]/10" : "bg-[var(--background)]",
      )}
    >
      <div
        className={cn(
          "flex items-center gap-1.5 text-xs font-medium",
          failed ? "text-[var(--status-error)]" : "text-[var(--status-success)]",
        )}
      >
        <Database className="h-3 w-3 shrink-0" />
        {step.order}. {failed ? "查詢失敗" : "取得數據"}
      </div>
      <p className="mt-0.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {brief || "（無內容）"}
      </p>
      {raw.length > brief.length && (
        <details className="mt-1">
          <summary className="cursor-pointer list-none text-xs text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]">
            顯示完整回傳值（供稽核）
          </summary>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-sm bg-[var(--muted)] p-2 font-mono text-xs leading-relaxed text-[var(--muted-foreground)]">
            {raw}
          </pre>
        </details>
      )}
    </div>
  );
}
