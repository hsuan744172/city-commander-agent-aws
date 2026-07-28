import { useState } from "react";
import IncidentUpload from "./IncidentUpload";
import AdvisoryCard from "./AdvisoryCard";

export default function IncidentTab() {
  const [report, setReport] = useState(null);

  return (
    <div className="space-y-4">
      <IncidentUpload onResult={setReport} />
      {report && report.advisories?.length > 0 && (
        <div className="space-y-4">
          <div className="text-xs text-gray-500">
            {report.generated_at} — {report.processed}/{report.total_incidents} 件處理完成
          </div>
          {report.advisories.map((adv, idx) => (
            <AdvisoryCard key={idx} advisory={adv} />
          ))}
        </div>
      )}
    </div>
  );
}
