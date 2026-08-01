import { Clock, Eye, Route, Siren, TrafficCone, Users } from "lucide-react";
import RouteCandidateTable from "./RouteCandidateTable";
import { cn } from "../lib/utils";

/**
 * SOP 第 1 條自動應變
 *
 * 只有城市應變觸發路段（忠孝東路四段、光復南路）會啟動應變：
 *   B 級 → 長綠燈時制（替代道路綠燈 +25%）＋ 調度警力淨空路口
 *   A 級 → 上述再加上第 2 條替代路徑引導
 * 其餘路段達 A/B 級只做燈號顯示，列在下方「僅監控」，不會誤導成已下應變指令。
 */
export default function AutoAdvisoryPanel({ advisories, monitoredAlerts, onInspect }) {
  const hasAdvisories = advisories.length > 0;
  const hasMonitored = monitoredAlerts.length > 0;

  if (!hasAdvisories && !hasMonitored) {
    return (
      <div className="bg-[var(--muted)] border border-[var(--border)] rounded-lg px-5 py-3 flex items-center gap-2">
        <span className="w-2 h-2 bg-[var(--status-success)] rounded-full" />
        <span className="text-sm text-[var(--muted-foreground)]">
          路網運作正常，未達 SOP 預警門檻
        </span>
      </div>
    );
  }

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Siren className="w-4 h-4 text-[var(--status-error)]" />
        <h2 className="text-sm font-semibold">SOP 第 1 條自動應變</h2>
        <span className="text-xs text-[var(--muted-foreground)]">
          僅城市應變觸發路段
        </span>
      </div>

      {hasAdvisories ? (
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
              {onInspect && (
                <button
                  type="button"
                  onClick={() => onInspect({ segment_id: adv.segment_id })}
                  className="shrink-0 px-2 py-1 rounded-sm text-xs border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
                >
                  詳情
                </button>
              )}
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
            {adv.police_dispatch?.officers > 0 && (
              <div className="flex items-start gap-1.5 text-xs">
                <Users className="w-3.5 h-3.5 mt-0.5 shrink-0 text-[var(--status-info)]" />
                <span className="text-[var(--muted-foreground)]">
                  {adv.police_dispatch.instruction}，共{" "}
                  {adv.police_dispatch.officers} 名警力（每路口{" "}
                  {adv.police_dispatch.per_intersection} 人）
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
        ))
      ) : (
        <p className="text-sm text-[var(--muted-foreground)]">
          城市應變觸發路段目前未達級別，無須啟動長綠燈時制。
        </p>
      )}

      {/* 僅監控：非觸發路段 */}
      {hasMonitored && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--muted)] px-3 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <Eye className="w-3 h-3 text-[var(--muted-foreground)]" />
            <span className="text-[10px] font-semibold text-[var(--muted-foreground)]">
              其他達級別路段（依 SOP 第 1 條僅供燈號顯示，不啟動應變）
            </span>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {monitoredAlerts.map((m) => (
              <span key={m.segment_id} className="text-xs text-[var(--muted-foreground)]">
                {m.road_name}
                <span
                  className={cn(
                    "ml-1 font-medium",
                    m.level === "A"
                      ? "text-[var(--status-error)]"
                      : "text-[var(--status-warning)]",
                  )}
                >
                  {m.level}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
