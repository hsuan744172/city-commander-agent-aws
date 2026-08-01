import { useState } from "react";
import { Activity, AlertTriangle, BarChart3, Bot, Shield, Siren } from "lucide-react";
import { cn } from "./lib/utils";
import useNetworkStatus from "./lib/useNetworkStatus";
import DashboardTab from "./components/DashboardTab";
import IncidentTab from "./components/IncidentTab";
import InjectionTab from "./components/InjectionTab";
import ChatTab from "./components/ChatTab";
import TimelineControl from "./components/TimelineControl";

const TABS = [
  { id: "dashboard", label: "即時儀表板", icon: BarChart3 },
  { id: "incidents", label: "路網即時監控", icon: Activity },
  { id: "injection", label: "事件注入", icon: Siren },
  { id: "chat", label: "AI 策略顧問", icon: Bot },
];

const INITIAL_CHAT = [
  {
    role: "assistant",
    content:
      "我是城市應變指揮官 AI 策略顧問。\n\n您可以向我提出任何 What-if 假設情境，例如：\n" +
      "• 若 BL17 人數增至 40,000 人怎麼辦？\n" +
      "• 忠孝東路與光復南路同時癱瘓的應變策略？\n" +
      "• 目前哪些基地台漫遊率超過 30%？\n" +
      "• 若 RD_TPE_003 封閉，主疏散路徑是哪一條、為什麼排除其他候選？\n\n" +
      "我會呼叫路網計算工具取得確定性結果，並依據 SOP 條款回答。",
  },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  // 儀表板與監控頁共用單一路段選取來源，避免聚焦、釘選與自動追蹤互相覆蓋。
  const [selectedSegmentId, setSelectedSegmentId] = useState(null);
  const [chatMessages, setChatMessages] = useState(INITIAL_CHAT);
  const [chatSessionId] = useState(
    () => `commander_${Math.random().toString(36).slice(2, 10)}`,
  );

  // 路網狀態只訂閱一次，全部分頁共用同一份，不會有多個輪詢／多條 WS。
  const network = useNetworkStatus();

  const inspectSegment = (segment) => {
    if (!segment?.segment_id) return;
    setSelectedSegmentId(segment.segment_id);
    setActiveTab("incidents");
  };

  const alertCount =
    network.segments.filter((s) => s.level === "A" || s.level === "B").length +
    (network.dataTriggers?.triggered_numbers?.length || 0);

  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)] flex flex-col">
      <header className="bg-[var(--card)] border-b border-[var(--border)] px-6 py-3 shadow-xs">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="bg-[var(--primary)] p-2 rounded-lg">
              <Shield className="w-5 h-5 text-[var(--primary-foreground)]" />
            </div>
            <h1 className="text-lg font-bold">城市應變指揮官</h1>
            {network.timestamp && (
              <span className="text-xs font-mono text-[var(--muted-foreground)]">
                {network.timestamp}
              </span>
            )}
          </div>

          <nav className="flex gap-1" aria-label="主要功能">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                    active
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--accent-foreground)] hover:bg-[var(--accent)]",
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                  {tab.id === "dashboard" && alertCount > 0 && (
                    <span className="ml-0.5 px-1.5 rounded-full bg-[var(--status-error)] text-[var(--primary-foreground)] text-[10px] font-bold">
                      {alertCount}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="flex-1 w-full max-w-[1600px] mx-auto px-6 py-4">
        {network.error && (
          <div className="mb-3 flex items-center gap-2 rounded-md border border-[var(--status-error)]/40 bg-[var(--status-error)]/10 px-3 py-2 text-sm text-[var(--status-error)]">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            無法取得路網狀態（{network.error}）；畫面顯示的可能是先前的資料。
          </div>
        )}

        <TimelineControl
          clock={network.clock}
          dataMode={network.dataMode}
          transport={network.transport}
          onChanged={network.refresh}
        />

        {/* 分頁保持掛載，切換時保留注入草稿、發布進度與顧問對話。 */}
        <div className={cn(activeTab !== "dashboard" && "hidden")}>
          <DashboardTab network={network} onInspectSegment={inspectSegment} />
        </div>

        <div className={cn(activeTab !== "incidents" && "hidden")}>
          <IncidentTab
            network={network}
            selectedSegmentId={selectedSegmentId}
            onSelectSegment={setSelectedSegmentId}
            onBackToDashboard={() => setActiveTab("dashboard")}
          />
        </div>

        <div className={cn(activeTab !== "injection" && "hidden")}>
          <InjectionTab />
        </div>

        <div className={cn(activeTab !== "chat" && "hidden")}>
          <ChatTab
            messages={chatMessages}
            onMessagesChange={setChatMessages}
            sessionId={chatSessionId}
            initialMessages={INITIAL_CHAT}
            simTime={network.timestamp}
          />
        </div>
      </main>
    </div>
  );
}
