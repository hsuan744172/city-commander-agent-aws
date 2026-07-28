import { AlertTriangle, ArrowRight } from "lucide-react";

export default function AlertTicker({ segments }) {
  const alerts = [];

  // A 級警報
  const critical = segments.filter((s) => s.level === "A");
  for (const seg of critical) {
    alerts.push({
      level: "critical",
      text: `${seg.road_name} 飽和度 ${Math.round(seg.saturation_score * 100)}% 已達 A 級癱瘓，建議立即啟動替代路徑引導`,
    });
  }

  // B 級警報
  const congested = segments.filter((s) => s.level === "B");
  if (congested.length > 0) {
    alerts.push({
      level: "warning",
      text: `${congested.map((s) => s.road_name).join("、")} 等 ${congested.length} 路段達 B 級壅擠，已建議啟動長綠燈時制`,
    });
  }

  // 低速警報
  const slowSegments = segments.filter((s) => s.avg_speed <= 10 && s.level !== "A");
  for (const seg of slowSegments) {
    alerts.push({
      level: "info",
      text: `${seg.road_name} 平均車速僅 ${seg.avg_speed} km/h，接近停滯，請密切關注`,
    });
  }

  if (alerts.length === 0) {
    return (
      <div className="bg-green-900/20 border border-green-800/40 rounded-xl px-5 py-3 flex items-center gap-2">
        <span className="w-2 h-2 bg-green-500 rounded-full" />
        <span className="text-sm text-green-300">路網運作正常，無異常預警</span>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-2">
      <div className="flex items-center gap-2 mb-1">
        <AlertTriangle className="w-4 h-4 text-red-400" />
        <span className="text-xs font-semibold text-gray-300">AI 智慧熱區預警</span>
      </div>
      {alerts.map((alert, idx) => (
        <div
          key={idx}
          className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm ${
            alert.level === "critical"
              ? "bg-red-900/30 border border-red-800/50 text-red-200"
              : alert.level === "warning"
              ? "bg-yellow-900/20 border border-yellow-800/40 text-yellow-200"
              : "bg-blue-900/20 border border-blue-800/40 text-blue-200"
          }`}
        >
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
            alert.level === "critical" ? "bg-red-500 animate-pulse" : alert.level === "warning" ? "bg-yellow-400" : "bg-blue-400"
          }`} />
          <span className="flex-1">{alert.text}</span>
          <ArrowRight className="w-3.5 h-3.5 opacity-50 shrink-0" />
        </div>
      ))}
    </div>
  );
}
