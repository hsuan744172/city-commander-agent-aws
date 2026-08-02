import { Clock, Eye, Route, Siren, TrafficCone, Users } from "lucide-react";
import RouteCandidateTable from "./RouteCandidateTable";
import { cn } from "../lib/utils";

/**
 * SOP 第 1 條判定與自動應變（單一路段）
 *
 * 只有城市應變觸發路段（忠孝東路四段、光復南路）會啟動應變：
 *   B 級 → 長綠燈時制（替代道路綠燈 +25%）＋ 調度警力淨空路口
 *   A 級 → 上述再加上第 2 條替代路徑引導
 * 非觸發路段達 A/B 級只列入監控（monitoredAlert），不會誤導成已下應變指令。
 *
 * 路段未達 A/B 級時本面板不輸出任何內容：分級狀態已在頁首標示，
 * 不需要在下方重複「未達門檻」。
 *
 * triggerSegmentNames 由呼叫端從後端 is_trigger_segment 推導後傳入，
 * 前端不自行寫死觸發路段名單（規則常數單一來源在 sop_rules.py）。
 */
export default function AutoAdvisoryPanel({
  advisories,
  monitoredAlert,
  triggerSegmentNames = [],
}) {
  const hasAdvisories = advisories.length > 0;

  if (!hasAdvisories && !monitoredAlert) return null;

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Siren
          className={cn(
            "w-4 h-4",
            hasAdvisories
              ? "text-[var(--status-error)]"
              : "text-[var(--muted-foreground)]",
          )}
        />
        <h2 className="text-sm font-semibold">
          {hasAdvisories ? "SOP 第 1 條自動應變" : "SOP 第 1 條判定"}
        </h2>
      </div>

      {hasAdvisories &&
        advisories.map((adv) => (
          <article
            key={adv.segment_id}
            className="rounded-md border border-[var(--border)] bg-[var(--muted)] p-3 space-y-2"
          >
            <div className="flex items-start gap-2">
              <span
                className={cn(
                  "w-2 h-2 rounded-full mt-1.5 shrink-0",
                  adv.level === "A"
                    ? "bg-[var(--status-error)] animate-pulse"
                    : "bg-[var(--status-warning)]",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{adv.triggered_by}</div>
                <div className="text-xs text-[var(--muted-foreground)] mt-0.5">
                  {adv.sop_reference}
                </div>
              </div>
            </div>

            {/* A 級才有替代路徑引導 */}
            {adv.primary_route && (
              <div className="bg-[var(--card)] rounded-md border border-[var(--border)] px-3 py-2 space-y-1">
                <div className="flex items-center gap-1.5 text-xs">
                  <Route className="w-3.5 h-3.5 text-[var(--status-success)] shrink-0" />
                  <span className="font-medium">主疏散：{adv.primary_route}</span>
                  <span className="text-[var(--muted-foreground)]">
                    飽和度 {Math.round((adv.primary_saturation || 0) * 100)}%
                  </span>
                </div>
                {adv.selection_reason && (
                  <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
                    {adv.selection_reason}
                  </p>
                )}
                {adv.secondary_routes?.length > 0 && (
                  <div className="text-xs text-[var(--muted-foreground)]">
                    次要疏散：
                    {adv.secondary_routes
                      .map(
                        (r) =>
                          `${r.name}（${Math.round((r.saturation_score || 0) * 100)}%）`,
                      )
                      .join("、")}
                  </div>
                )}
                {adv.route_candidates?.length > 0 && (
                  <RouteCandidateTable
                    candidates={adv.route_candidates}
                    upstream={adv.upstream_resolution}
                  />
                )}
              </div>
            )}

            {/* 號誌配時：SOP 第 1 條是 alternatives 全集，不是只有主疏散一條 */}
            {adv.signal_plan?.adjustments?.length > 0 && (
              <div className="flex items-start gap-1.5 text-xs">
                <TrafficCone className="w-3.5 h-3.5 mt-0.5 shrink-0 text-[var(--status-warning)]" />
                <div className="min-w-0">
                  <span className="text-[var(--foreground)]">
                    {adv.signal_plan.adjustments
                      .map((a) => a.road_name)
                      .join("、")}{" "}
                    綠燈配時 +25%（長綠燈時制）
                  </span>
                  {adv.window && (
                    <div className="text-[var(--muted-foreground)] mt-0.5">{adv.window}</div>
                  )}
                </div>
              </div>
            )}

            {/* 警力淨空路口：SOP 第 1 條明列，原本完全沒有輸出 */}
            {adv.police_dispatch?.instruction && (
              <div className="flex items-start gap-1.5 text-xs">
                <Users className="w-3.5 h-3.5 mt-0.5 shrink-0 text-[var(--status-info)]" />
                <span className="text-[var(--muted-foreground)]">
                  {adv.police_dispatch.instruction}
                  {adv.police_dispatch.staffing_note && (
                    <span className="block mt-0.5">{adv.police_dispatch.staffing_note}</span>
                  )}
                </span>
              </div>
            )}

            {adv.ete_minutes != null && (
              <div className="flex items-start gap-1.5 text-xs">
                <Clock className="w-3.5 h-3.5 mt-0.5 shrink-0 text-[var(--status-info)]" />
                <div className="min-w-0">
                  <span className="text-[var(--foreground)]">
                    預估恢復時間 {adv.ete_minutes} 分鐘
                  </span>
                  {adv.ete_breakdown && (
                    <div className="text-[var(--muted-foreground)] mt-0.5 leading-relaxed">
                      基礎清除 {adv.ete_breakdown.base_clearance_minutes} ＋ 壅塞懲罰{" "}
                      {adv.ete_breakdown.congestion_penalty_minutes}（受影響路段平均飽和度{" "}
                      {Math.round((adv.ete_breakdown.avg_saturation_score || 0) * 100)}%）
                      <br />
                      {adv.ete_breakdown.severity_basis}
                    </div>
                  )}
                </div>
              </div>
            )}
          </article>
        ))}

      {/* 本路段達 A/B 級，但不是 SOP 第 1 條指定的城市應變觸發路段 */}
      {monitoredAlert && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--muted)] px-3 py-2 flex items-start gap-1.5">
          <Eye className="w-3.5 h-3.5 mt-0.5 shrink-0 text-[var(--muted-foreground)]" />
          <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
            本路段
            <span
              className={cn(
                "mx-1 font-medium",
                monitoredAlert.level === "A"
                  ? "text-[var(--status-error)]"
                  : "text-[var(--status-warning)]",
              )}
            >
              {monitoredAlert.level_description}
            </span>
            （飽和度 {Math.round((monitoredAlert.saturation_score || 0) * 100)}%、時速{" "}
            {monitoredAlert.avg_speed} 公里），不在 SOP 第 1 條列舉的城市應變觸發路段
            {triggerSegmentNames.length > 0 && `（${triggerSegmentNames.join("、")}）`}
            內，因此只做紅黃燈顯示與監控，不啟動長綠燈時制與替代路徑引導。
          </p>
        </div>
      )}
    </div>
  );
}
