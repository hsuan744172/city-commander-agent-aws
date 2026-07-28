import { useState } from "react";
import { ChevronDown, ChevronUp, Route, Clock, TrafficCone, AlertCircle, BookOpen, Copy, Send, Check } from "lucide-react";
import CMSInline from "./CMSInline";

export default function AdvisoryCard({ advisory }) {
  const [expanded, setExpanded] = useState(true);

  if (advisory.error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-xl p-4 flex items-center gap-2 text-red-300 text-sm">
        <AlertCircle className="w-4 h-4 shrink-0" />
        <span>{advisory.event_id}：{advisory.error}</span>
      </div>
    );
  }

  const eid = advisory.event_identification || {};
  const traffic = advisory.traffic_classification || {};
  const route = advisory.route_advisory || {};
  const ete = route.ete_estimate;
  const primary = route.primary_evacuation_route;
  const comms = advisory.public_communications || {};

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 bg-gray-800/60 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-3">
          <LevelBadge level={traffic.max_level} />
          <span className="text-sm font-bold">{advisory.event_id}</span>
          <span className="text-xs text-gray-400">{eid.location}</span>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
      </div>

      {expanded && (
        <div className="p-5 space-y-4">
          {/* Summary */}
          <p className="text-sm text-gray-100 font-medium leading-relaxed">{advisory.summary}</p>

          {/* 1. SOP 觸發 */}
          {eid.triggered_sop_articles?.length > 0 && (
            <Section icon={BookOpen} title="觸發 SOP 條款" color="yellow">
              {eid.triggered_sop_articles.map((s, i) => (
                <div key={i} className="text-sm text-yellow-100/90">
                  <span className="font-semibold">第 {s.sop_number} 條 {s.title}</span>
                  <span className="text-yellow-200/60 ml-2">— {s.reason}</span>
                </div>
              ))}
            </Section>
          )}

          {/* 2. 交通分級 */}
          {traffic.congestion_details?.length > 0 && (
            <Section icon={AlertCircle} title="交通分級判定依據" color="orange">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {traffic.congestion_details.map((c, i) => (
                  <div key={i} className="bg-gray-800/50 rounded-lg px-3 py-2">
                    <div className="text-xs text-gray-400">{c.road_name}</div>
                    <div className={`text-sm font-bold ${c.level === "A" ? "text-red-400" : c.level === "B" ? "text-yellow-400" : "text-green-400"}`}>
                      飽和度 {Math.round(c.saturation_score * 100)}%
                    </div>
                    <div className="text-xs text-gray-500">{c.description}</div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* 3. 路徑建議 */}
          {primary && (
            <Section icon={Route} title="替代路徑建議" color="green">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="bg-green-600 text-xs px-2 py-0.5 rounded font-bold">主疏散</span>
                  <span className="text-sm font-semibold text-green-100">{primary.primary_route_name}</span>
                  <span className="text-xs text-green-300/60">容量 {primary.capacity_vph} 車/時 ・ 飽和度 {Math.round(primary.current_saturation * 100)}%</span>
                </div>
                <div className="text-xs text-green-200/70">決策依據：{primary.selection_reason}</div>
                {primary.congestion_note && <div className="text-xs text-yellow-300 bg-yellow-900/20 px-3 py-1.5 rounded">{primary.congestion_note}</div>}

                {primary.secondary_routes?.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-green-800/30 space-y-1">
                    <div className="text-xs text-green-400/60 font-medium">次要替代路線：</div>
                    {primary.secondary_routes.map((r, i) => (
                      <div key={i} className="text-xs text-green-200/60 flex justify-between">
                        <span>{r.name}</span>
                        <span>飽和度 {Math.round(r.saturation_score * 100)}% ・ {r.is_upstream ? "上游" : "下游"}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Section>
          )}

          {/* 4. ETE */}
          {ete && (
            <Section icon={Clock} title="預估恢復時間 (ETE)" color="blue">
              <div className="flex items-baseline gap-3">
                <span className="text-3xl font-bold text-blue-100">{ete.ete_minutes}</span>
                <span className="text-sm text-blue-300">分鐘</span>
              </div>
              <div className="text-xs text-blue-300/70 mt-1 space-y-0.5">
                <div>基礎清除時間：{ete.base_clearance_minutes} 分鐘（嚴重度：{ete.severity}）</div>
                <div>壅塞懲罰：{ete.congestion_penalty_minutes} 分鐘（平均飽和度 {Math.round(ete.avg_saturation_score * 100)}%）</div>
                <div className="text-blue-400/50 mt-1">{ete.formula}</div>
                <div className="text-blue-400/50">來源：{ete.calculation_source}</div>
              </div>
            </Section>
          )}

          {/* 5. 號誌調整 */}
          {route.signal_adjustments?.length > 0 && (
            <Section icon={TrafficCone} title="號誌調整指令" color="purple">
              {route.signal_adjustments.map((s, i) => (
                <div key={i} className="text-sm text-purple-200">
                  <span className="font-medium">{s.road_name}</span>：{s.action}
                  {s.note && <span className="text-xs text-purple-300/60 ml-2">（{s.note}）</span>}
                </div>
              ))}
            </Section>
          )}

          {/* 內嵌多語通報 (SOP 6) */}
          <CMSInline comms={comms} eventId={advisory.event_id} />

          {/* Errors */}
          {advisory.errors?.length > 0 && (
            <div className="text-xs text-red-400 space-y-0.5">
              {advisory.errors.map((e, i) => <div key={i}>⚠ {e}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ icon: Icon, title, color, children }) {
  const colors = {
    yellow: "bg-yellow-900/15 border-yellow-800/40",
    orange: "bg-orange-900/15 border-orange-800/40",
    green: "bg-green-900/15 border-green-800/40",
    blue: "bg-blue-900/15 border-blue-800/40",
    purple: "bg-purple-900/15 border-purple-800/40",
  };
  const iconColors = {
    yellow: "text-yellow-400",
    orange: "text-orange-400",
    green: "text-green-400",
    blue: "text-blue-400",
    purple: "text-purple-400",
  };
  return (
    <div className={`rounded-lg border p-4 ${colors[color]}`}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`w-4 h-4 ${iconColors[color]}`} />
        <span className={`text-xs font-semibold ${iconColors[color]}`}>{title}</span>
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function LevelBadge({ level }) {
  const s = { A: "bg-red-600", B: "bg-yellow-500 text-black", Normal: "bg-green-600" };
  const l = { A: "A 級癱瘓", B: "B 級壅擠", Normal: "正常" };
  return <span className={`px-2 py-0.5 rounded text-xs font-bold ${s[level] || s.Normal}`}>{l[level] || "正常"}</span>;
}
