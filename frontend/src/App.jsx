import { useState } from "react";
import { Shield, BarChart3, FileText, Bot } from "lucide-react";
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

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      {/* Global Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-blue-600 p-2 rounded-lg">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <h1 className="text-lg font-bold text-white">城市應變指揮官</h1>
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
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition ${
                    active
                      ? "bg-blue-600 text-white"
                      : "text-gray-400 hover:text-white hover:bg-gray-800"
                  }`}
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
        {activeTab === "dashboard" && <DashboardTab />}
        {activeTab === "incidents" && <IncidentTab />}
        {activeTab === "chat" && <ChatTab />}
      </main>
    </div>
  );
}
