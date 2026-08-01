import { useState } from "react";
import { Shield, BarChart3, FileText, Bot } from "lucide-react";
import { cn } from "./lib/utils";
import DashboardTab from "./components/DashboardTab";
import IncidentTab from "./components/IncidentTab";
import ChatTab from "./components/ChatTab";

const TABS = [
  { id: "dashboard", label: "即時儀表板", icon: BarChart3 },
  { id: "incidents", label: "事件處置與建議書", icon: FileText },
  { id: "chat", label: "AI 策略顧問", icon: Bot },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  // 儀表板點擊路段/小卡後要在建議書頁聚焦的路段
  const [focusSegmentId, setFocusSegmentId] = useState(null);

  // 從儀表板跳往「事件處置與建議書」並帶上該路段
  const inspectSegment = (segment) => {
    if (!segment?.segment_id) return;
    setFocusSegmentId(segment.segment_id);
    setActiveTab("incidents");
  };

  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)] flex flex-col">
      {/* Global Header */}
      <header className="bg-[var(--card)] border-b border-[var(--border)] px-6 py-3 shadow-xs">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-[var(--primary)] p-2 rounded-lg">
              <Shield className="w-5 h-5 text-[var(--primary-foreground)]" />
            </div>
            <h1 className="text-lg font-bold">城市應變指揮官</h1>
          </div>

          {/* Tab Navigation */}
          <nav className="flex gap-1">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition",
                    active
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--accent-foreground)] hover:bg-[var(--accent)]"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      {/* Tab Content */}
      <main className="flex-1 p-4 max-w-[1600px] mx-auto w-full">
        {activeTab === "dashboard" && <DashboardTab onInspectSegment={inspectSegment} />}
        {activeTab === "incidents" && (
          <IncidentTab
            focusSegmentId={focusSegmentId}
            onClearFocus={() => setFocusSegmentId(null)}
            onBackToDashboard={() => setActiveTab("dashboard")}
          />
        )}
        {activeTab === "chat" && <ChatTab />}
      </main>
    </div>
  );
}
