import { AlertTriangle, ArrowRight, Route, Clock } from "lucide-react";

export default function AlertTicker({ segments, autoAdvisories }) {
  const advisories = autoAdvisories || [];
  const critical = segments.filter((s) => s.level === "A");
  const congested = segments.filter((s) => s.level === "B");

  // 無異常
  if (critical.length === 0 && congested.length === 0) {
    return (
      <div className="bg-green-900/20 border border-green-800/40 rounded-xl px-5 py-3 flex items-center gap-2">
        <span className="w-2 h-2 bg-green-500 rounded-full" />
        <span className="text-sm text-green-600">路網運作正常，無異常預警</span>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <AlertTriangle className="w-4 h-4 text-red-400" />
        <span className="text-xs font-semibold text-gray-700">AI 智慧預警與自動路徑引導</span>
      </div>

      {/* A 級：SOP 1 → 2 自動路徑引導 */}
      {advisories.map((adv, idx) => (
        <div key={idx} className="bg-red-900/20 border border-red-800/50 rounded-lg p-3 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
            <span className="text-sm text-red-700 font-medium">{adv.triggered_by}</span>
          </div>
          <div className="text-xs text-red-600">{adv.sop_reference}</div>

          {adv.primary_route && (
            <div className="flex items-center gap-2 mt-1 bg-red-900/30 px-3 py-2 rounded">
              <Route className="w-3.5 h-3.5 text-green-400 shrink-0" />
              <div className="text-xs text-green-700">
                <span className="font-semibold">替代路徑：{adv.primary_route}</span>
                <span className="text-green-600 ml-2">
                  (飽和度 {Math.round((adv.primary_saturation || 0) * 100)}%)
                </span>
              </div>
            </div>
          )}

          {adv.signal_action && (
            <div className="text-xs text-purple-600 pl-6">號誌調整：{adv.signal_action}</div>
          )}

          {adv.ete_minutes && (
            <div className="flex items-center gap-1.5 text-xs text-blue-600 pl-6">
              <Clock className="w-3 h-3" />
              預估恢復時間：{adv.ete_minutes} 分鐘
            </div>
          )}

          {adv.selection_reason && (
            <div className="text-xs text-gray-500 pl-6">依據：{adv.selection_reason}</div>
          )}
        </div>
      ))}

      {/* B 級壅擠提示 */}
      {congested.length > 0 && (
        <div className="bg-yellow-900/15 border border-yellow-800/40 rounded-lg px-4 py-2.5 flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-yellow-400 rounded-full shrink-0" />
          <span className="text-sm text-yellow-700">
            {congested.map((s) => s.road_name).join("、")} 等 {congested.length} 路段達 B 級壅擠，已啟動長綠燈時制
          </span>
        </div>
      )}
    </div>
  );
}
