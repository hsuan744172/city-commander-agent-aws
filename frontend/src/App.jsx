import { useEffect, useState } from "react";
import { AlertTriangle, BarChart3, Bot, FileText, Shield, Siren } from "lucide-react";
import { cn } from "./lib/utils";
import useNetworkStatus from "./lib/useNetworkStatus";
import DashboardTab from "./components/DashboardTab";
import IncidentTab from "./components/IncidentTab";
import InjectionTab from "./components/InjectionTab";
import ChatTab from "./components/ChatTab";
import TimelineControl from "./components/TimelineControl";

const TABS = [
  { id: "dashboard", label: "即時儀表板", icon: BarChart3 },
  { id: "injection", label: "事件注入", icon: Siren },
  { id: "incidents", label: "事件處置與建議書", icon: FileText },
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
  // 儀表板點擊路段/小卡後要在建議書頁聚焦的路段
  const [focusSegmentId, setFocusSegmentId] = useState(null);
  // 最近一次注入產出的建議書；事件處置頁以此為主要來源
  const [injectedReport, setInjectedReport] = useState(null);
  // 對話紀錄提到最上層：切換分頁不會再把整段對話清空
  const [chatMessages, setChatMessages] = useState(INITIAL_CHAT);
  const [chatSessionId] = useState(
    () => `commander_${Math.random().toString(36).slice(2, 10)}`,
  );

  // 路網狀態只訂閱一次，全部分頁共用同一份，不會有多個輪詢／多條 WS
  const network = useNetworkStatus();

  // 其他值班席位注入事件時後端會推播建議書，直接接住並跳到建議書頁
  useEffect(() => {
    if (!network.pushedReport?.report) return;
    setInjectedReport(network.pushedReport.report);
  }, [network.pushedReport]);

  // 從儀表板跳往「事件處置與建議書」並帶上該路段
  const inspectSegment = (segment) => {
    if (!segment?.segment_id) return;
    setFocusSegmentId(segment.segment_id);
    setActiveTab("incidents");
  };

  // 注入完成後直接把建議書帶到事件處置頁
  const showInjectedReport = (report) => {
    setInjectedReport(report || null);
    setFocusSegmentId(null);
    setActiveTab("incidents");
  };

  const alertCount =
    network.segments.filter((s) => s.level === "A" || s.level === "B").length +
    (network.dataTriggers?.triggered_numbers?.length || 0);

  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)] flex flex-col">
      {/* Global Header */}
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

          {/* Tab Navigation */}
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

      <main className="flex-1 p-4 max-w-[1600px] mx-auto w-full space-y-4">
        {/* 連線異常要明講，不能讓畫面停在舊資料卻毫無提示 */}
        {network.error && (
          <div
            role="alert"
            className="flex items-center gap-2 px-4 py-2.5 rounded-md bg-[var(--status-error)]/10 border border-[var(--status-error)]/30 text-sm text-[var(--status-error)]"
          >
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

        {/*
          分頁全部保持掛載，只用 CSS 切換顯示。
          原本用條件渲染會 unmount，切一次分頁就把建議書與整段對話清空，
          評審看完建議書想回儀表板再回來就得重新注入。
        */}
        <div className={cn(activeTab !== "dashboard" && "hidden")}>
          <DashboardTab network={network} onInspectSegment={inspectSegment} />
        </div>

        <div className={cn(activeTab !== "injection" && "hidden")}>
          <InjectionTab onInjected={showInjectedReport} />
        </div>

        <div className={cn(activeTab !== "incidents" && "hidden")}>
          <IncidentTab
            network={network}
            report={injectedReport}
            focusSegmentId={focusSegmentId}
            onClearFocus={() => setFocusSegmentId(null)}
            onBackToDashboard={() => setActiveTab("dashboard")}
            onOpenInjection={() => setActiveTab("injection")}
          />
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
