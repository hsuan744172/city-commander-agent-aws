import { useState } from "react";
import IncidentUpload from "./IncidentUpload";
import IncidentMap from "./IncidentMap";
import AdvisoryCard from "./AdvisoryCard";

export default function IncidentTab() {
  const [report, setReport] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(0);

  const advisories = report?.advisories || [];
  const selectedAdvisory = advisories[selectedIdx] || null;

  return (
    <div className="space-y-4">
      {/* 上傳區 */}
      <IncidentUpload onResult={(data) => { setReport(data); setSelectedIdx(0); }} />

      {/* 雙欄戰情室 */}
      {advisories.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4" style={{ minHeight: "600px" }}>
          {/* 左側：地圖 */}
          <div className="h-[600px]">
            <IncidentMap advisory={selectedAdvisory} />
          </div>

          {/* 右側：事件卡片列表 */}
          <div className="space-y-3 overflow-y-auto max-h-[600px] pr-1">
            <div className="text-xs text-gray-400 mb-1">
              {report.generated_at} — {report.processed}/{report.total_incidents} 件處理完成
            </div>
            {advisories.map((adv, idx) => (
              <AdvisoryCard
                key={idx}
                advisory={adv}
                isSelected={idx === selectedIdx}
                onSelect={() => setSelectedIdx(idx)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
