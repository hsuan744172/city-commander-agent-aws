import { useEffect, useState } from "react";
import { Activity } from "lucide-react";

function levelStyle(level) {
  if (level === "A") return { bg: "bg-red-600", text: "text-red-100", bar: "bg-red-500" };
  if (level === "B") return { bg: "bg-yellow-500", text: "text-yellow-900", bar: "bg-yellow-400" };
  return { bg: "bg-green-600", text: "text-green-100", bar: "bg-green-500" };
}

export default function TrafficStatusBar() {
  const [segments, setSegments] = useState([]);
  const [ts, setTs] = useState("");

  useEffect(() => {
    fetch("/api/status")
      .then((r) => r.json())
      .then((data) => {
        setSegments(data.segments || []);
        setTs(data.timestamp || "");
      })
      .catch(() => {});
  }, []);

  const aCount = segments.filter((s) => s.level === "A").length;
  const bCount = segments.filter((s) => s.level === "B").length;

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-400" />
          <h2 className="text-sm font-semibold text-gray-200">即時路網監測</h2>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {aCount > 0 && <span className="bg-red-600 px-2 py-0.5 rounded font-bold">{aCount} 癱瘓</span>}
          {bCount > 0 && <span className="bg-yellow-500 text-black px-2 py-0.5 rounded font-bold">{bCount} 壅擠</span>}
          <span className="text-gray-500">{ts}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-8 gap-2">
        {segments.map((seg) => {
          const style = levelStyle(seg.level);
          const pct = Math.round(seg.saturation_score * 100);
          return (
            <div key={seg.segment_id} className="bg-gray-800 rounded-lg p-2 text-center">
              <div className="text-xs text-gray-400 truncate mb-1">{seg.road_name}</div>
              <div className="w-full bg-gray-700 rounded-full h-2 mb-1">
                <div className={`h-2 rounded-full ${style.bar}`} style={{ width: `${pct}%` }} />
              </div>
              <div className={`text-xs font-bold ${pct >= 95 ? "text-red-400" : pct >= 85 ? "text-yellow-400" : "text-green-400"}`}>
                {pct}%
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
