import { Check, Languages, Radar } from "lucide-react";
import { cn } from "../lib/utils";

/**
 * 資料型 SOP 條款的主動偵測（第 3 條捷運分流、第 4 條大巨蛋散場、第 6 條多語通報）
 *
 * 這三條的觸發條件是純資料條件，不需要事件注入。原本系統只在事件處置時才評估，
 * 所以儀表板不會主動預警；而第 4 條完全沒有實作。這個面板讓「智慧指揮官主動
 * 針對數據趨勢提供預警」有具體畫面。
 */
export default function SopTriggerPanel({ dataTriggers, dataAsOf, className = "" }) {
  const checks = dataTriggers?.checks || [];
  const triggeredNumbers = dataTriggers?.triggered_numbers || [];
  const roamingStations = dataTriggers?.roaming_trigger_stations || [];

  if (checks.length === 0) {
    return (
      <div
        className={cn(
          "bg-[var(--card)] rounded-lg border border-[var(--border)] p-4",
          className,
        )}
      >
        <PanelHeader count={0} dataAsOf={dataAsOf} />
        <p className="text-sm text-[var(--muted-foreground)]">等待人流資料</p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "bg-[var(--card)] rounded-lg border border-[var(--border)] p-4 flex flex-col gap-3",
        className,
      )}
    >
      <PanelHeader count={triggeredNumbers.length} dataAsOf={dataAsOf} />

      {/* 儀表板不往下捲，條款過多時在面板內部捲動 */}
      <ul className="space-y-2 overflow-y-auto min-h-0">
        {checks.map((check) => (
          <li
            key={check.sop_number}
            className={cn(
              "rounded-md border px-3 py-2.5",
              check.triggered
                ? "border-[var(--status-warning)]/40 bg-[var(--status-warning)]/10"
                : "border-[var(--border)] bg-[var(--muted)]",
            )}
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded-sm font-bold",
                  check.triggered
                    ? "bg-[var(--status-warning)] text-[var(--primary-foreground)]"
                    : "bg-[var(--secondary)] text-[var(--muted-foreground)]",
                )}
              >
                SOP {check.sop_number}
              </span>
              <span className="text-sm font-medium">{check.sop_title}</span>
              <span
                className={cn(
                  "text-xs ml-auto",
                  check.triggered
                    ? "text-[var(--status-warning)] font-medium"
                    : "text-[var(--muted-foreground)]",
                )}
              >
                {check.triggered ? "已觸發" : "未觸發"}
              </span>
            </div>

            <p className="text-xs text-[var(--muted-foreground)] mt-1 leading-relaxed">
              {check.reason}
            </p>

            {check.triggered && check.actions?.length > 0 && (
              <ul className="mt-1.5 space-y-0.5">
                {check.actions.map((action, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-1 text-xs text-[var(--foreground)]"
                  >
                    <Check className="w-3 h-3 mt-0.5 shrink-0 text-[var(--status-success)]" />
                    {action}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      {/* SOP 第 6 條的判定證據：哪一站、多少 %。原本只在 JSON 裡，畫面看不到 */}
      {roamingStations.length > 0 && (
        <div className="rounded-md bg-[var(--chart-5)]/10 px-3 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <Languages className="w-3 h-3 text-[var(--chart-5)]" />
            <span className="text-[10px] font-semibold text-[var(--chart-5)]">
              漫遊率達標站點（全市掃描，任一站達 30% 即須多語通報）
            </span>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {roamingStations.map((s) => (
              <span key={s.bs_id} className="text-xs text-[var(--foreground)]">
                {s.location_name}
                <span className="ml-1 font-mono font-medium text-[var(--chart-5)]">
                  {s.roaming_user_pct_display}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PanelHeader({ count, dataAsOf }) {
  return (
    <div className="flex items-center justify-between gap-2 mb-1">
      <div className="flex items-center gap-2">
        <Radar className="w-4 h-4 text-[var(--primary)]" />
        <h2 className="text-sm font-semibold">SOP 自動偵測</h2>
        {count > 0 && (
          <span className="bg-[var(--status-warning)] text-[var(--primary-foreground)] px-2 py-0.5 rounded-full text-[10px] font-bold">
            {count} 條觸發
          </span>
        )}
      </div>
      {dataAsOf && (
        <span className="text-xs text-[var(--muted-foreground)] font-mono">{dataAsOf}</span>
      )}
    </div>
  );
}
