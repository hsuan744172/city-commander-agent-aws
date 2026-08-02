import { useState } from "react";
import { Activity, AlertTriangle, BarChart3, Shield, Siren } from "lucide-react";
import { cn } from "./lib/utils";
import useNetworkStatus from "./lib/useNetworkStatus";
import DashboardTab from "./components/DashboardTab";
import IncidentTab from "./components/IncidentTab";
import InjectionTab from "./components/InjectionTab";
import FloatingAdvisor from "./components/FloatingAdvisor";
import useStreamClock from "./lib/useStreamClock";

const TABS = [
  { id: "dashboard", label: "即時儀表板", icon: BarChart3 },
  { id: "incidents", label: "路網即時監控", icon: Activity },
  { id: "injection", label: "事件注入", icon: Siren },
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

  // 串流播放器決定「現在看的是哪個時間」。LIVE 時交給後端時鐘與 WS 推播，
  // 回看時改用 /api/status?ts= 取當時的路網，不會動到後端全域時鐘。
  const stream = useStreamClock();
  const playheadTs = stream.isLive ? null : stream.playheadStamp || null;
  // 路網狀態只訂閱一次，全部分頁共用同一份，不會有多個輪詢／多條 WS。
  const network = useNetworkStatus(playheadTs);

  const inspectSegment = (segment) => {
    if (!segment?.segment_id) return;
    setSelectedSegmentId(segment.segment_id);
    setActiveTab("incidents");
  };

  const alertCount =
    network.segments.filter((s) => s.level === "A" || s.level === "B").length +
    (network.dataTriggers?.triggered_numbers?.length || 0);

  return (
    // h-screen + overflow-hidden：儀表板以「剩餘高度」排版，一個畫面看完不必往下捲；
    // 其他分頁需要長內容，改由各自的容器內部捲動。
    <div className="h-screen overflow-hidden bg-[var(--background)] text-[var(--foreground)] flex flex-col">
      <header className="shrink-0 bg-[var(--card)] border-b border-[var(--border)] px-6 py-3 shadow-xs">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="bg-[var(--primary)] p-2 rounded-lg">
              <Shield className="w-5 h-5 text-[var(--primary-foreground)]" />
            </div>
            {/* 模擬時間不在標題旁重複顯示：時間軸的播放頭讀數（含秒）才是唯一來源 */}
            <h1 className="text-lg font-bold">城市應變指揮官</h1>
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

      <main className="flex-1 min-h-0 w-full max-w-[1600px] mx-auto px-6 py-4 flex flex-col gap-3">
        {network.error && (
          <div className="shrink-0 flex items-center gap-2 rounded-md border border-[var(--status-error)]/40 bg-[var(--status-error)]/10 px-3 py-2 text-sm text-[var(--status-error)]">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            無法取得路網狀態（{network.error}）；畫面顯示的可能是先前的資料。
          </div>
        )}

        {/* 分頁保持掛載，切換時保留注入草稿、發布進度與顧問對話。 */}
        {/* 儀表板剛好填滿剩餘高度，本身不捲動 */}
        <div className={cn("flex-1 min-h-0", activeTab !== "dashboard" && "hidden")}>
          <DashboardTab
            network={network}
            stream={stream}
            onInspectSegment={inspectSegment}
          />
        </div>

        <div
          className={cn(
            "flex-1 min-h-0 overflow-y-auto",
            activeTab !== "incidents" && "hidden",
          )}
        >
          <IncidentTab
            network={network}
            selectedSegmentId={selectedSegmentId}
            onSelectSegment={setSelectedSegmentId}
            onBackToDashboard={() => setActiveTab("dashboard")}
          />
        </div>

        {/* 事件注入自己撐滿剩餘高度，左右兩欄各自捲動，整頁不出現外層捲軸 */}
        <div className={cn("flex-1 min-h-0", activeTab !== "injection" && "hidden")}>
          <InjectionTab />
        </div>
      </main>

      {/*
        顧問改成儀表板右下角的浮動聊天室：只在主頁出現，避免蓋住監控頁的地圖操作
        與事件注入的表單。對話紀錄由 App 保管，離開主頁再回來仍是同一段對話。
      */}
      {activeTab === "dashboard" && (
        <FloatingAdvisor
          messages={chatMessages}
          onMessagesChange={setChatMessages}
          sessionId={chatSessionId}
          initialMessages={INITIAL_CHAT}
          simTime={network.timestamp}
        />
      )}
    </div>
  );
}
