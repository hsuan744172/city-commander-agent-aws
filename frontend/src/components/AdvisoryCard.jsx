import { useState } from "react";
import { ChevronDown, ChevronUp, Route, Clock, Send, Copy, Check, AlertTriangle } from "lucide-react";
import CMSInline from "./CMSInline";

export default function AdvisoryCard({ advisory, isSelected, onSelect }) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (advisory.error) {
    const isApiError = advisory.error.includes("API") || advisory.error.includes("http") || advisory.error.includes("503");
    return (
      <div className={`rounded-xl p-4 border cursor-pointer transition ${isSelected ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-white hover:bg-gray-50"}`} onClick={onSelect}>
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-500" />
          <span className="text-sm text-amber-700">
            {isApiError ? "AI 顧問忙碌中，已切換至 SOP 備援模式" : `${advisory.event_id} 處理異常`}
          </span>
        </div>
      </div>
    );
  }

  const eid = advisory.event_identification || {};
  const traffic = advisory.traffic_classification || {};
  const route = advisory.route_advisory || {};
  const ete = route.ete_estimate;
  const primary = route.primary_evacuation_route;
  const comms = advisory.public_communications || {};
  const special = advisory.special_advisory;

  const handleCopy = () => {
    const text = advisory.ai_narrative || advisory.summary || "";
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div
      className={`rounded-xl border transition cursor-pointer ${isSelected ? "border-blue-400 ring-2 ring-blue-100 bg-blue-50/30" : "border-gray-200 bg-white hover:border-gray-300"}`}
      onClick={onSelect}
    >
      {/* === 頂部摘要 (三秒決策) === */}
      <div className="p-4">
        {/* Row 1: ID + Severity + SOP */}
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <span className="text-sm font-bold text-gray-900">{advisory.event_id}</span>
          <SeverityBadge severity={eid.severity} />
          <LevelBadge level={traffic.max_level} />
          {eid.triggered_sop_articles?.map((s, i) => (
            <span key={i} className="text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded font-medium">
              SOP {s.sop_number}
            </span>
          ))}
        </div>

        {/* Row 2: Location */}
        <div className="text-sm text-gray-600 mb-3">{eid.location || eid.affected_segment}</div>

        {/* Row 3: Key metrics */}
        <div className="flex items-center gap-4 flex-wrap">
          {/* 主疏散路徑 */}
          {primary && (
            <div className="flex items-center gap-1.5">
              <Route className="w-4 h-4 text-green-500" />
              <span className="text-sm font-medium text-green-700">{primary.primary_route_name}</span>
            </div>
          )}

          {/* ETE 大字 */}
          {ete && (
            <div className="flex items-center gap-1.5">
              <Clock className="w-4 h-4 text-blue-500" />
              <span className="text-xl font-bold text-blue-700">{ete.ete_minutes}</span>
              <span className="text-xs text-blue-500">分鐘</span>
            </div>
          )}

          {/* 特殊處置 (SOP3/5) */}
          {special && !primary && (
            <span className="text-sm text-cyan-700 font-medium">{special.title}</span>
          )}
        </div>

        {/* Row 4: Action buttons */}
        <div className="flex items-center gap-2 mt-3">
          <button
            onClick={(e) => { e.stopPropagation(); handleCopy(); }}
            className="flex items-center gap-1 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded-lg text-xs text-gray-600 transition"
          >
            {copied ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
            {copied ? "已複製" : "複製建議書"}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setDetailOpen(!detailOpen); }}
            className="flex items-center gap-1 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded-lg text-xs text-gray-600 transition"
          >
            {detailOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {detailOpen ? "收合詳情" : "展開詳情"}
          </button>
        </div>
      </div>

      {/* === 折疊詳情 (Accordion) === */}
      {detailOpen && (
        <div className="border-t border-gray-100 px-4 pb-4 pt-3 space-y-3" onClick={(e) => e.stopPropagation()}>
          {/* AI 建議書敘述 */}
          {advisory.ai_narrative && (
            <div className="bg-blue-50 rounded-lg p-3">
              <div className="text-[10px] font-semibold text-blue-500 mb-1">AI 決策分析</div>
              <div className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{advisory.ai_narrative}</div>
            </div>
          )}

          {/* 交通分級 */}
          {traffic.congestion_details?.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-gray-400 mb-1">交通分級依據</div>
              {traffic.congestion_details.map((c, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="text-gray-600">{c.road_name}</span>
                  <span className={`font-bold ${c.level === "A" ? "text-red-500" : c.level === "B" ? "text-amber-500" : "text-green-500"}`}>
                    {Math.round(c.saturation_score * 100)}% {c.description}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* 路徑選擇理由 */}
          {primary?.selection_reason && (
            <div>
              <div className="text-[10px] font-semibold text-gray-400 mb-1">路徑選擇依據</div>
              <div className="text-sm text-gray-600">{primary.selection_reason}</div>
              {primary.secondary_routes?.length > 0 && (
                <div className="text-xs text-gray-400 mt-1">
                  次要替代：{primary.secondary_routes.map(r => `${r.name}(${Math.round(r.saturation_score*100)}%)`).join("、")}
                </div>
              )}
            </div>
          )}

          {/* 特殊處置細節 */}
          {special?.actions && (
            <div>
              <div className="text-[10px] font-semibold text-gray-400 mb-1">{special.title}</div>
              <ul className="text-sm text-gray-600 space-y-0.5">
                {special.actions.map((a, i) => <li key={i}>• {a}</li>)}
              </ul>
            </div>
          )}

          {/* 號誌調整 */}
          {route.signal_adjustments?.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-gray-400 mb-1">號誌調整</div>
              {route.signal_adjustments.map((s, i) => (
                <div key={i} className="text-sm text-gray-600">{s.road_name}：{s.action}</div>
              ))}
            </div>
          )}

          {/* 多語通報 */}
          <CMSInline comms={comms} eventId={advisory.event_id} />
        </div>
      )}
    </div>
  );
}

function SeverityBadge({ severity }) {
  const s = {
    Critical: "bg-red-600 text-white px-2 py-0.5",
    High: "bg-orange-500 text-white px-2 py-0.5",
    Medium: "bg-yellow-500 text-black px-2 py-0.5",
  };
  return severity ? (
    <span className={`text-xs rounded-md font-bold ${s[severity] || "bg-gray-200 text-gray-600 px-2 py-0.5"}`}>
      {severity}
    </span>
  ) : null;
}

function LevelBadge({ level }) {
  const s = { A: "bg-red-100 text-red-600 border border-red-200", B: "bg-amber-100 text-amber-600 border border-amber-200", Normal: "bg-green-100 text-green-600 border border-green-200" };
  const l = { A: "A 級", B: "B 級", Normal: "正常" };
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${s[level] || s.Normal}`}>{l[level] || "正常"}</span>;
}
