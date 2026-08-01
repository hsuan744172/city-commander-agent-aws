import { useEffect, useState } from "react";
import { CheckCircle2, Timer } from "lucide-react";
import AdvisoryCard from "./AdvisoryCard";
import IncidentMap from "./IncidentMap";
import StreetCam from "./StreetCam";
import { cn } from "../lib/utils";

/** 注入完成後的單頁事件處置工作區：地圖、街景、建議書與公眾通報保持在同一脈絡。 */
export default function IncidentResponsePanel({ report }) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const advisories = report?.advisories || [];
  const selectedAdvisory = advisories[selectedIdx] || advisories[0] || null;

  useEffect(() => {
    setSelectedIdx(0);
  }, [report]);

  if (!report) return null;

  return (
    <section className="space-y-4" aria-labelledby="incident-response-title">
      <div className="flex items-start justify-between gap-3 flex-wrap rounded-lg border border-[var(--status-success)]/40 bg-[var(--status-success)]/10 p-4">
        <div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-[var(--status-success)]" />
            <h2 id="incident-response-title" className="text-lg font-semibold">
              即時事件處置建議書
            </h2>
          </div>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            已完成事件辨識、SOP 比對、替代路徑、恢復時間與公眾通報，可直接在本頁執行處置。
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap text-xs text-[var(--muted-foreground)]">
          {report.generated_at && <span>產出時間 {report.generated_at}</span>}
          <span>
            {report.processed ?? 0}/{report.total_incidents ?? advisories.length} 件完成
          </span>
          {report.elapsed_seconds != null && (
            <span
              title="從事件注入到建議書完成的端到端時間"
              className={cn(
                "flex items-center gap-1 rounded-sm px-2 py-1 font-medium",
                report.within_budget
                  ? "bg-[var(--status-success)]/20 text-[var(--status-success)]"
                  : "bg-[var(--status-error)]/15 text-[var(--status-error)]",
              )}
            >
              <Timer className="w-3 h-3" />
              {report.elapsed_seconds} 秒 / 預算 {report.budget_seconds ?? 60} 秒
            </span>
          )}
        </div>
      </div>

      {advisories.length === 0 ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 text-sm text-[var(--muted-foreground)]">
          本次注入未產出可顯示的事件建議書，請查看上方失敗數量或後端紀錄。
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
          <div className="space-y-4 xl:sticky xl:top-4">
            <div className="h-[340px]">
              <IncidentMap advisory={selectedAdvisory} />
            </div>
            <StreetCam advisory={selectedAdvisory} />
          </div>

          <div className="space-y-3">
            {advisories.map((advisory, idx) => (
              <AdvisoryCard
                key={advisory.event_id || idx}
                advisory={advisory}
                isSelected={idx === selectedIdx}
                onSelect={() => setSelectedIdx(idx)}
                defaultExpanded={idx === 0}
              />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
