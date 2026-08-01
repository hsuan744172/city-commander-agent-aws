import { AlertTriangle, Route, Clock } from "lucide-react";

export default function AlertTicker({ segments, autoAdvisories }) {
  const advisories = autoAdvisories || [];
  const critical = segments.filter((s) => s.level === "A");
  const congested = segments.filter((s) => s.level === "B");

  if (critical.length === 0 && congested.length === 0) {
    return (
      <div className="bg-[var(--muted)] border border-[var(--border)] rounded-lg px-5 py-3 flex items-center gap-2">
        <span className="w-2 h-2 bg-[var(--status-success)] rounded-full" />
        <span className="text-sm text-[var(--muted-foreground)]">路網運作正常，無異常預警</span>
      </div>
    );
  }

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <AlertTriangle className="w-4 h-4 text-[var(--muted-foreground)]" />
        <span className="text-xs font-semibold text-[var(--foreground)] uppercase tracking-wide">AI 智慧預警與自動路徑引導</span>
      </div>

      {/* A 級：SOP 1 → 2 自動路徑引導 */}
      {advisories.map((adv, idx) => (
        <div key={idx} className="bg-[var(--muted)] border border-[var(--border)] rounded-md p-3 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-[var(--status-error)] rounded-full animate-pulse" />
            <span className="text-sm font-medium text-[var(--foreground)]">{adv.triggered_by}</span>
          </div>
          <div className="text-xs text-[var(--muted-foreground)]">{adv.sop_reference}</div>

          {adv.primary_route && (
            <div className="flex items-center gap-2 mt-1 bg-[var(--card)] px-3 py-2 rounded-md border border-[var(--border)]">
              <Route className="w-3.5 h-3.5 text-[var(--muted-foreground)] shrink-0" />
              <div className="text-xs text-[var(--foreground)]">
                <span className="font-medium">替代路徑：{adv.primary_route}</span>
                <span className="text-[var(--muted-foreground)] ml-2">
                  (飽和度 {Math.round((adv.primary_saturation || 0) * 100)}%)
                </span>
              </div>
            </div>
          )}

          {adv.signal_action && (
            <div className="text-xs text-[var(--muted-foreground)] pl-6">號誌調整：{adv.signal_action}</div>
          )}

          {adv.ete_minutes && (
            <div className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)] pl-6">
              <Clock className="w-3 h-3" />
              預估恢復時間：{adv.ete_minutes} 分鐘
            </div>
          )}

          {adv.selection_reason && (
            <div className="text-xs text-[var(--muted-foreground)] pl-6">依據：{adv.selection_reason}</div>
          )}
        </div>
      ))}

      {/* B 級壅擠提示 */}
      {congested.length > 0 && (
        <div className="bg-[var(--muted)] border border-[var(--border)] rounded-md px-4 py-2.5 flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-[var(--status-warning)] rounded-full shrink-0" />
          <span className="text-sm text-[var(--muted-foreground)]">
            {congested.map((s) => s.road_name).join("、")} 等 {congested.length} 路段達 B 級壅擠，已啟動長綠燈時制
          </span>
        </div>
      )}
    </div>
  );
}
