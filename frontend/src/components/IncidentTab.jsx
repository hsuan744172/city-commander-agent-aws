import { useState } from "react";
import IncidentUpload from "./IncidentUpload";
import IncidentMap from "./IncidentMap";
import AdvisoryCard from "./AdvisoryCard";
import StreetCam from "./StreetCam";

export default function IncidentTab() {
  const [report, setReport] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(0);

  const advisories = report?.advisories || [];
  const selectedAdvisory = advisories[selectedIdx] || null;

  return (
    <div className="space-y-4">
      <IncidentUpload onResult={(data) => { setReport(data); setSelectedIdx(0); }} />

      {advisories.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* 左側：地圖 + 事故路段即時影像 */}
          <div className="space-y-4">
            <div className="h-[340px]">
              <IncidentMap advisory={selectedAdvisory} />
            </div>
            <StreetCam advisory={selectedAdvisory} />
          </div>

          {/* 右側：事件卡片列表 */}
          <div className="space-y-3 overflow-y-auto max-h-[760px] pr-1">
            <div className="text-xs text-[var(--muted-foreground)] mb-1">
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
