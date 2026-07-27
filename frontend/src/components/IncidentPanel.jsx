import { useState } from "react";
import { AlertTriangle, Zap, Users, Send, Loader2 } from "lucide-react";

const PRESETS = [
  {
    label: "路面塌陷",
    sub: "Critical・光復南路封閉",
    icon: AlertTriangle,
    color: "border-red-500 hover:bg-red-950",
    activeColor: "border-red-400 bg-red-950",
    data: { event_id: "TPE_2026_ACC_001", type: "Road_Collapse_Accident", location: "光復南路與忠孝東路口南側", affected_segment: "RD_TPE_002", status: "Closed", severity: "Critical", description: "地下管線爆裂路面塌陷三車追撞，光復南路南下全線封鎖", timestamp: "2026-05-20 22:10" },
  },
  {
    label: "捷運人潮推擠",
    sub: "High・BL17 站散場湧出",
    icon: Users,
    color: "border-orange-500 hover:bg-orange-950",
    activeColor: "border-orange-400 bg-orange-950",
    data: { event_id: "TPE_2026_EVT_002", type: "Crowd_Surge_Injury", location: "捷運國父紀念館站 5 號出口", affected_segment: "BS_MRT_BL17", status: "Restricted", severity: "High", description: "散場人群推擠受傷，救護車佔用單向車道", timestamp: "2026-05-20 22:20" },
  },
  {
    label: "號誌故障",
    sub: "Medium・信義區號誌失效",
    icon: Zap,
    color: "border-yellow-500 hover:bg-yellow-950",
    activeColor: "border-yellow-400 bg-yellow-950",
    data: { event_id: "TPE_2026_EVT_003", type: "Power_Failure", location: "信義威秀/ATT4FUN周邊", affected_segment: "RD_TPE_007", status: "Caution", severity: "Medium", description: "信義區部分路段號誌失效，需改由人工交通指揮", timestamp: "2026-05-20 22:30" },
  },
];

export default function IncidentPanel({ onInject, loading }) {
  const [selected, setSelected] = useState([]);

  const toggle = (idx) => setSelected((prev) => prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx]);

  const handleSend = () => {
    const incidents = selected.map((idx) => PRESETS[idx].data);
    if (incidents.length > 0) onInject(incidents);
  };

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <h2 className="text-sm font-semibold text-gray-200 mb-3">模組二：突發事件注入</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {PRESETS.map((p, idx) => {
          const Icon = p.icon;
          const active = selected.includes(idx);
          return (
            <button key={idx} onClick={() => toggle(idx)} className={`flex items-start gap-3 p-4 rounded-lg border transition-all text-left ${active ? p.activeColor : `border-gray-700 bg-gray-800/50 ${p.color}`}`}>
              <Icon className="w-5 h-5 mt-0.5 shrink-0" />
              <div>
                <div className="text-sm font-medium text-gray-100">{p.label}</div>
                <div className="text-xs text-gray-400 mt-0.5">{p.sub}</div>
              </div>
            </button>
          );
        })}
      </div>
      <button onClick={handleSend} disabled={loading || selected.length === 0} className="mt-4 w-full flex items-center justify-center gap-2 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg font-medium text-sm transition">
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        {loading ? "AI 決策運算中..." : `注入 ${selected.length} 件事件`}
      </button>
    </div>
  );
}
