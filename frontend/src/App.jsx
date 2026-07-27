import { useState, useCallback } from "react";
import Header from "./components/Header";
import TrafficStatusBar from "./components/TrafficStatusBar";
import AlertBanner from "./components/AlertBanner";
import IncidentPanel from "./components/IncidentPanel";
import AdvisoryReport from "./components/AdvisoryReport";
import ChatPanel from "./components/ChatPanel";
import CMSPanel from "./components/CMSPanel";

const API_BASE = "/api";

export default function App() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [alert, setAlert] = useState(null);

  const handleInject = useCallback(async (incidents) => {
    setLoading(true);
    setAlert(null);
    try {
      const res = await fetch(`${API_BASE}/incidents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ incidents }),
      });
      const data = await res.json();
      setReport(data);

      // 自動彈出警報
      if (data.advisories?.length > 0) {
        const adv = data.advisories[0];
        if (adv.traffic_classification?.max_level === "A") {
          setAlert({ level: "A", summary: adv.summary, event_id: adv.event_id });
        } else if (adv.traffic_classification?.max_level === "B") {
          setAlert({ level: "B", summary: adv.summary, event_id: adv.event_id });
        }
      }
    } catch (e) {
      setAlert({ level: "error", summary: e.message });
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <Header />
      <AlertBanner alert={alert} onDismiss={() => setAlert(null)} />

      <div className="p-4 space-y-4">
        {/* 模組一：即時路網狀態 */}
        <TrafficStatusBar />

        <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
          {/* 左側：事件注入 + 建議書 */}
          <div className="xl:col-span-3 space-y-4">
            {/* 模組二：事件注入 */}
            <IncidentPanel onInject={handleInject} loading={loading} />

            {/* 模組二：建議書 */}
            {report && <AdvisoryReport report={report} />}

            {/* 模組五：多語通報 */}
            {report && <CMSPanel report={report} />}
          </div>

          {/* 右側：模組三四 AI 對話 */}
          <div className="xl:col-span-1">
            <ChatPanel />
          </div>
        </div>
      </div>
    </div>
  );
}
