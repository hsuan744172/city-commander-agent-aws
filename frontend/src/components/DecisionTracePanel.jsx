import { ChevronDown, ChevronRight, Cpu, GitBranch } from "lucide-react";
import { useState } from "react";
import { cn } from "../lib/utils";
import { ENGINE_STYLES } from "../lib/aiLabels";

/**
 * 決策鏈（模組 4：判定依據展示）
 *
 * 對應命題「在 Dashboard 上清楚展示 AI 的推理過程，並引用 SOP 分級表解釋為何判定
 * 為 A 級及為何排除特定替代道路」。
 *
 * 設計重點是「分工要看得出來」：每一步都掛一個徽章標明是程式運算還是 AI 生成，
 * 並列出該步的權威模組、套用的條文／公式與輸入數值。原本這些資訊只存在後端，
 * 畫面上只看到一段 AI 文字，評審無法分辨哪個數字是算出來的。
 *
 * 版面刻意做成報告的欄位表而不是段落文字：一行一步，數值靠右對齊，
 * 細節收在展開區，掃視時能一眼看完全流程。
 */
export default function DecisionTracePanel({ trace }) {
  const steps = trace?.steps || [];
  if (steps.length === 0) return null;

  const split = trace.engine_split || {};

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <header className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] px-4 py-2.5">
        <GitBranch className="h-4 w-4 text-[var(--primary)]" />
        <h3 className="text-sm font-semibold">決策鏈</h3>
        <span className="text-xs text-[var(--muted-foreground)]">
          {trace.total_steps} 步
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <SplitChip engine="deterministic" count={split.deterministic} />
          <SplitChip engine="llm" count={split.llm} />
        </div>
      </header>

      {split.statement && (
        <p className="flex items-start gap-1.5 border-b border-[var(--border)] bg-[var(--muted)] px-4 py-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
          <Cpu className="mt-0.5 h-3 w-3 shrink-0" />
          {split.statement}
        </p>
      )}

      <ol className="divide-y divide-[var(--border)]">
        {steps.map((step) => (
          <li key={step.id}>
            <TraceRow step={step} />
          </li>
        ))}
      </ol>
    </section>
  );
}

function SplitChip({ engine, count }) {
  if (!count) return null;
  const style = ENGINE_STYLES[engine];
  return (
    <span
      className={cn(
        "rounded-sm border px-1.5 py-0.5 text-[10px] font-medium",
        style.cls,
      )}
    >
      {style.label} {count}
    </span>
  );
}

function TraceRow({ step }) {
  const [open, setOpen] = useState(false);
  const style = ENGINE_STYLES[step.engine] || ENGINE_STYLES.deterministic;
  const hasDetail =
    (step.inputs?.length || 0) > 0 || step.rule || step.formula || step.detail;

  return (
    <div className={cn(step.engine === "llm" && "bg-[var(--status-info)]/5")}>
      <button
        type="button"
        onClick={() => hasDetail && setOpen((value) => !value)}
        aria-expanded={hasDetail ? open : undefined}
        disabled={!hasDetail}
        className={cn(
          "flex w-full items-start gap-2.5 px-4 py-2.5 text-left transition",
          hasDetail && "hover:bg-[var(--accent)]/40",
          !hasDetail && "cursor-default",
        )}
      >
        <span className="mt-0.5 w-5 shrink-0 text-right font-mono text-xs text-[var(--muted-foreground)]">
          {step.order}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className={cn(
                "rounded-sm border px-1.5 py-0.5 text-[10px] font-medium",
                style.cls,
              )}
            >
              {step.engine_label || style.label}
            </span>
            <span className="text-[10px] text-[var(--muted-foreground)]">
              {step.stage}
            </span>
            <span className="text-sm font-medium">{step.title}</span>
            {step.sop_articles?.map((article) => (
              <span
                key={article}
                className="rounded-sm bg-[var(--status-warning)]/15 px-1.5 py-0.5 text-[10px] font-medium text-[var(--status-warning)]"
              >
                SOP {article}
              </span>
            ))}
          </div>

          <p className="mt-1 text-sm leading-relaxed text-[var(--muted-foreground)]">
            {step.output}
          </p>
        </div>

        {hasDetail &&
          (open ? (
            <ChevronDown className="mt-1 h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
          ) : (
            <ChevronRight className="mt-1 h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
          ))}
      </button>

      {open && hasDetail && (
        <div className="space-y-2 border-t border-dashed border-[var(--border)] px-4 py-2.5 pl-11">
          {step.rule && (
            <Labelled label="套用規則">{step.rule}</Labelled>
          )}
          {step.formula && (
            <Labelled label="公式">
              <code className="font-mono text-xs">{step.formula}</code>
            </Labelled>
          )}

          {step.inputs?.length > 0 && (
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                依據數值
              </div>
              <dl className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
                {step.inputs.map((field, index) => (
                  <div
                    key={`${field.label}-${index}`}
                    className="flex flex-wrap gap-x-3 gap-y-0.5 px-2.5 py-1.5"
                  >
                    <dt className="w-40 shrink-0 text-xs text-[var(--muted-foreground)]">
                      {field.label}
                    </dt>
                    <dd className="min-w-0 flex-1 text-xs">{field.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {step.detail && <Labelled label="判定說明">{step.detail}</Labelled>}

          {step.authority && (
            <Labelled label="權威模組">
              <code className="font-mono text-[10px]">{step.authority}</code>
            </Labelled>
          )}
        </div>
      )}
    </div>
  );
}

function Labelled({ label, children }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5">
      <span className="w-40 shrink-0 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </span>
      <span className="min-w-0 flex-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {children}
      </span>
    </div>
  );
}
