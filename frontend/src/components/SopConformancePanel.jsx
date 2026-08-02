import { useState } from "react";
import { ChevronDown, ChevronRight, ShieldCheck, ShieldX } from "lucide-react";
import { cn } from "../lib/utils";
import { CONFORMANCE_STYLES } from "../lib/aiLabels";

/**
 * SOP 逐項合規檢核
 *
 * 官方三個預設注入事件分別對應 SOP 第 2、3、5 條。這份表把每一條的「觸發要件」與
 * 「處置步驟」拆成逐項可勾稽的檢核，資料來自 backend/agents/decision_trace.py
 * 的確定性投影，不是請 AI 自述有沒有遵守。
 *
 * 評分標準有 35% 在「應引用之 SOP 條款是否正確、替代路徑是否避開容量有限路段、
 * 分級判定是否符合 SOP 條件」，這張表就是現場逐條對照用的。
 */
export default function SopConformancePanel({ conformance }) {
  const articles = conformance?.articles || [];
  if (articles.length === 0) return null;

  const compliant = conformance.compliant;
  const StatusIcon = compliant ? ShieldCheck : ShieldX;

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <header
        className={cn(
          "flex flex-wrap items-center gap-2 border-b px-4 py-2.5",
          compliant
            ? "border-[var(--border)]"
            : "border-[var(--status-error)]/40 bg-[var(--status-error)]/5",
        )}
      >
        <StatusIcon
          className={cn(
            "h-4 w-4",
            compliant ? "text-[var(--status-success)]" : "text-[var(--status-error)]",
          )}
        />
        <h3 className="text-sm font-semibold">SOP 合規檢核</h3>
        <span
          className={cn(
            "rounded-sm px-1.5 py-0.5 text-[10px] font-bold",
            compliant
              ? "bg-[var(--status-success)]/15 text-[var(--status-success)]"
              : "bg-[var(--status-error)]/15 text-[var(--status-error)]",
          )}
        >
          {conformance.satisfied_checks}/{conformance.total_checks} 項滿足
        </span>
        {conformance.primary_articles?.length > 0 && (
          <span className="ml-auto text-xs text-[var(--muted-foreground)]">
            本事件主條款：
            {conformance.primary_articles.map((n) => `第 ${n} 條`).join("、")}
          </span>
        )}
      </header>

      <ul className="divide-y divide-[var(--border)]">
        {articles.map((article) => (
          <li key={article.sop_number}>
            <ArticleRow article={article} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function ArticleRow({ article }) {
  // 有未滿足項目時預設展開，指揮官不必自己去找哪裡出問題
  const [open, setOpen] = useState(article.failed_count > 0);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left transition hover:bg-[var(--accent)]/40"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
        )}

        <span className="rounded-sm bg-[var(--secondary)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--secondary-foreground)]">
          SOP {article.sop_number}
        </span>
        <span className="text-sm font-medium">{article.title}</span>

        {article.scope === "situational" && (
          <span className="rounded-sm bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
            全市態勢
          </span>
        )}
        {!article.triggered && (
          <span className="rounded-sm bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
            未觸發
          </span>
        )}

        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {article.degraded_count > 0 && (
            <span className="rounded-sm bg-[var(--status-warning)]/15 px-1.5 py-0.5 text-[10px] font-medium text-[var(--status-warning)]">
              退階 {article.degraded_count}
            </span>
          )}
          {article.failed_count > 0 && (
            <span className="rounded-sm bg-[var(--status-error)]/15 px-1.5 py-0.5 text-[10px] font-medium text-[var(--status-error)]">
              未滿足 {article.failed_count}
            </span>
          )}
          <span className="font-mono text-xs text-[var(--muted-foreground)]">
            {article.satisfied_count}/{article.total}
          </span>
        </span>
      </button>

      {open && (
        <div className="px-4 pb-3">
          {article.basis && (
            <p className="mb-1.5 text-[10px] text-[var(--muted-foreground)]">
              適用理由：{article.basis}
            </p>
          )}
          <ul className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
            {article.checks.map((check, index) => (
              <li
                key={`${check.clause}-${index}`}
                className="flex flex-wrap items-start gap-x-2 gap-y-1 px-2.5 py-1.5"
              >
                <StatusChip status={check.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-1.5">
                    {check.clause && (
                      <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">
                        {check.clause}
                      </span>
                    )}
                    <span className="text-xs leading-relaxed">{check.requirement}</span>
                  </div>
                  {check.evidence && (
                    <p className="mt-0.5 text-[10px] leading-relaxed text-[var(--muted-foreground)]">
                      佐證：{check.evidence}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StatusChip({ status }) {
  const style = CONFORMANCE_STYLES[status] || CONFORMANCE_STYLES.na;
  return (
    <span
      className={cn(
        "mt-0.5 w-16 shrink-0 rounded-sm px-1.5 py-0.5 text-center text-[10px] font-medium",
        style.cls,
      )}
    >
      {style.label}
    </span>
  );
}
