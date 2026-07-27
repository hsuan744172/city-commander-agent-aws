import { FileText, Route, AlertCircle, ChevronDown, ChevronUp, TrafficCone, Clock } from "lucide-react";
import { useState } from "react";

export default function AdvisoryReport({ report }) {
  if (!report?.advisories?.length) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <FileText className="w-5 h-5 text-blue-400" />
        <h2 className="text-sm font-semibold text-gray-200">交控中心建議書</h2>
        <span className="text-xs text-gray-500">{report.generated_at} ・ {report.processed}/{report.total_incidents} 件</span>
      </div>
      {report.advisories.map((adv, idx) => <AdvisoryCard key={idx} advisory={adv} />)}
    </div>
  );
}

function AdvisoryCard({ advisory }) {
  const [expanded, setExpanded] = useState(true);

  if (advisory.error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-xl p-4">
        <div className="flex items-center gap-2 text-red-300 text-sm"><AlertCircle className="w-4 h-4" />{advisory.event_id}: {advisory.error}</div>
      </div>
    );
  }

  const eid = advisory.event_identification || {};
  const traffic = advisory.traffic_classification || {};
  const route = advisory.route_advisory || {};
  const ete = route.ete_estimate;
  const primary = route.primary_evacuation_route;

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-800/50 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-3">
          <LevelBadge level={traffic.max_level} />
          <span className="text-sm font-bold text-white">{advisory.event_id}</span>
          <span className="text-xs text-gray-400">{eid.location}</span>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
      </div>

      {expanded && (
        <div className="p-4 space-y-4">
          {/* Summary */}
          <p className="text-sm text-gray-200 font-medium">{advisory.summary}</p>

          {/* SOP 觸發 */}
          {eid.triggered_sop_articles?.length > 0 && (
            <div className="bg-yellow-900/20 border border-yellow-800/50 rounded-lg p-3">
              <div className="text-xs font-semibold text-yellow-300 mb-1">觸發 SOP 條款</div>
              {eid.triggered_sop_articles.map((s, i) => (
                <div key={i} className="text-xs text-yellow-200/80">第 {s.sop_number} 條：{s.title} — {s.reason}</div>
              ))}
            </div>
          )}

          {/* 路徑建議 */}
          {primary && (
            <div className="bg-green-900/20 border border-green-800/50 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <Route className="w-4 h-4 text-green-400" />
                <span className="text-xs font-semibold text-green-300">主疏散路徑</span>
              </div>
              <div className="text-sm text-green-100 font-medium">{primary.primary_route_name}</div>
              <div className="text-xs text-green-300/70 mt-1">
                容量 {primary.capacity_vph} 車/時 ・ 飽和度 {Math.round(primary.current_saturation * 100)}%
                {primary.is_congested && " ⚠️ 已壅塞"}
              </div>
              <div className="text-xs text-green-300/60 mt-1">依據：{primary.selection_reason}</div>
              {primary.congestion_note && <div className="text-xs text-yellow-300 mt-1">{primary.congestion_note}</div>}

              {/* 次要路段 */}
              {primary.secondary_routes?.length > 0 && (
                <div className="mt-2 pt-2 border-t border-green-800/30">
                  <div className="text-xs text-green-400/60 mb-1">次要疏散路段：</div>
                  {primary.secondary_routes.map((r, i) => (
                    <div key={i} className="text-xs text-green-200/60">{r.name} (飽和 {Math.round(r.saturation_score * 100)}%)</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ETE */}
          {ete && (
            <div className="bg-blue-900/20 border border-blue-800/50 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <Clock className="w-4 h-4 text-blue-400" />
                <span className="text-xs font-semibold text-blue-300">預估恢復時間 (ETE)</span>
              </div>
              <div className="text-2xl font-bold text-blue-100">{ete.ete_minutes} 分鐘</div>
              <div className="text-xs text-blue-300/70 mt-1">
                基礎清除 {ete.base_clearance_minutes} 分 + 壅塞懲罰 {ete.congestion_penalty_minutes} 分
              </div>
              <div className="text-xs text-blue-300/50 mt-0.5">{ete.formula}</div>
              <div className="text-xs text-blue-300/50">來源：{ete.calculation_source}</div>
            </div>
          )}

          {/* 號誌調整 */}
          {route.signal_adjustments?.length > 0 && (
            <div className="bg-purple-900/20 border border-purple-800/50 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <TrafficCone className="w-4 h-4 text-purple-400" />
                <span className="text-xs font-semibold text-purple-300">號誌調整指令</span>
              </div>
              {route.signal_adjustments.map((s, i) => (
                <div key={i} className="text-xs text-purple-200">
                  {s.road_name}：{s.action} {s.note && `(${s.note})`}
                </div>
              ))}
            </div>
          )}

          {/* Errors */}
          {advisory.errors?.length > 0 && (
            <div className="text-xs text-red-400">{advisory.errors.map((e, i) => <div key={i}>⚠ {e}</div>)}</div>
          )}
        </div>
      )}
    </div>
  );
}

function LevelBadge({ level }) {
  const s = { A: "bg-red-600", B: "bg-yellow-500 text-black", Normal: "bg-green-600" };
  const l = { A: "A 級", B: "B 級", Normal: "正常" };
  return <span className={`px-2 py-0.5 rounded text-xs font-bold ${s[level] || s.Normal}`}>{l[level] || "正常"}</span>;
}
