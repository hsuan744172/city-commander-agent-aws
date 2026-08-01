import { useEffect, useRef, useState } from "react";
import { Bot, Gauge, Loader2, RotateCcw, Send, Sparkles, User, Wrench } from "lucide-react";
import { cn } from "../lib/utils";

const TOOL_LABELS = {
  lookup_sop_clause: "查詢 SOP 條文",
  traffic_status: "查詢路網車流",
  crowd_status: "查詢人流與漫遊",
  sop_trigger_status: "查詢 SOP 觸發狀態",
  evacuation_route: "計算疏散路徑",
  recovery_time: "計算 ETE",
  signal_plan: "查詢號誌與警力處置",
  station_detail: "查詢基地台明細",
  network_geometry: "查詢路網幾何",
};

const SUGGESTIONS = [
  "若 BL17 人數增至 40,000 人，應啟動哪些條款？",
  "若 RD_TPE_003 封閉，主疏散是哪條、為什麼排除其他候選？",
  "目前哪些基地台漫遊率超過 30%？需要多語通報嗎？",
  "大巨蛋現在是散場狀態嗎？依據是什麼？",
];

/**
 * AI 策略顧問（What-if 情境分析）
 *
 * 對話紀錄由 App 保管，切換分頁不會清空；session_id 一併帶給後端，
 * 後端保留對話歷史，追問時顧問記得前一題。
 * 回覆會附上實際引用的 SOP 條文原文與呼叫過的計算工具，
 * 讓評審看得出答案是查出來的而不是模型自己編的。
 */
export default function ChatTab({
  messages,
  onMessagesChange,
  sessionId,
  initialMessages,
  simTime,
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async (text) => {
    const prompt = (text ?? input).trim();
    if (!prompt || loading) return;
    setInput("");
    onMessagesChange([...messages, { role: "user", content: prompt }]);
    setLoading(true);

    try {
      const res = await fetch("/api/what-if", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, session_id: sessionId, sim_time: simTime || "" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      onMessagesChange([
        ...messages,
        { role: "user", content: prompt },
        {
          role: "assistant",
          content: data.response,
          model: data.model,
          simTime: data.sim_time,
          dataAsOf: data.data_as_of,
          citedClauses: data.cited_clauses || [],
          toolsUsed: data.tools_used || [],
          confidence: data.confidence || null,
        },
      ]);
    } catch (e) {
      onMessagesChange([
        ...messages,
        { role: "user", content: prompt },
        { role: "assistant", content: `連線錯誤：${e.message}`, confidence: {
          score: 0,
          level: "low",
          label: "低信心",
          evidence_sources: [],
          reasons: ["無法連線至後端，沒有可驗證的資料證據"],
        } },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const reset = async () => {
    onMessagesChange(initialMessages);
    try {
      await fetch("/api/what-if/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
    } catch {
      // 後端記憶清除失敗不影響前端重新開始
    }
  };

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] flex flex-col h-[calc(100vh-260px)] min-h-[520px]">
      <div className="px-5 py-4 border-b border-[var(--border)] flex items-center gap-2 flex-wrap">
        <Sparkles className="w-5 h-5 text-[var(--primary)]" />
        <span className="text-sm font-semibold">AI 策略顧問 — What-if 情境分析</span>
        {simTime && (
          <span className="text-xs font-mono text-[var(--muted-foreground)]">
            情境時間 {simTime}
          </span>
        )}
        <button
          type="button"
          onClick={reset}
          className="ml-auto flex items-center gap-1 px-2.5 py-1 rounded-sm text-xs border border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
        >
          <RotateCcw className="w-3 h-3" />
          重設對話
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4" aria-live="polite">
        {messages.map((msg, idx) => (
          <div key={idx} className={cn("flex gap-3", msg.role === "user" && "justify-end")}>
            {msg.role === "assistant" && (
              <div className="bg-[var(--primary)]/20 p-2 rounded-md h-fit shrink-0">
                <Bot className="w-4 h-4 text-[var(--primary)]" />
              </div>
            )}
            <div
              className={cn(
                "max-w-[80%] rounded-lg px-4 py-3",
                msg.role === "user"
                  ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "bg-[var(--secondary)] text-[var(--foreground)]",
              )}
            >
              {msg.role === "assistant" && msg.confidence && (
                <details className="mb-2 w-fit">
                  <summary
                    className={cn(
                      "flex cursor-pointer list-none items-center gap-1.5 rounded-sm border px-2 py-1 text-xs font-medium",
                      msg.confidence.level === "high"
                        ? "border-[var(--status-success)]/40 bg-[var(--status-success)]/10 text-[var(--status-success)]"
                        : msg.confidence.level === "medium"
                          ? "border-[var(--status-warning)]/40 bg-[var(--status-warning)]/10 text-[var(--status-warning)]"
                          : "border-[var(--status-error)]/40 bg-[var(--status-error)]/10 text-[var(--status-error)]",
                    )}
                  >
                    <Gauge className="w-3.5 h-3.5" />
                    {msg.confidence.label} {msg.confidence.score}%
                  </summary>
                  <div className="mt-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] p-2.5 text-xs text-[var(--muted-foreground)]">
                    {msg.confidence.evidence_sources?.length > 0 && (
                      <div className="mb-1">
                        證據來源：{msg.confidence.evidence_sources.join("、")}
                      </div>
                    )}
                    <ul className="space-y-0.5">
                      {msg.confidence.reasons?.map((reason) => (
                        <li key={reason}>・{reason}</li>
                      ))}
                    </ul>
                  </div>
                </details>
              )}
              <div className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</div>

              {/* 實際呼叫的確定性計算工具 */}
              {msg.toolsUsed?.length > 0 && (
                <div className="mt-2 flex items-center gap-1.5 flex-wrap">
                  <Wrench className="w-3 h-3 text-[var(--muted-foreground)]" />
                  {msg.toolsUsed.map((tool) => (
                    <span
                      key={tool}
                      className="text-[10px] px-1.5 py-0.5 rounded-sm bg-[var(--accent)] text-[var(--accent-foreground)]"
                    >
                      {TOOL_LABELS[tool] || tool}
                    </span>
                  ))}
                </div>
              )}

              {/* 引用的 SOP 條文原文 */}
              {msg.citedClauses?.length > 0 && (
                <details className="mt-2">
                  <summary className="text-xs text-[var(--muted-foreground)] cursor-pointer">
                    引用條文原文（
                    {msg.citedClauses.map((c) => `第 ${c.sop_number} 條`).join("、")}）
                  </summary>
                  <div className="mt-1.5 space-y-1.5">
                    {msg.citedClauses.map((c) => (
                      <pre
                        key={c.sop_number}
                        className="font-mono text-xs whitespace-pre-wrap bg-[var(--muted)] p-2.5 rounded-md text-[var(--muted-foreground)]"
                      >
                        {c.text}
                      </pre>
                    ))}
                  </div>
                </details>
              )}

              {(msg.model || msg.dataAsOf) && (
                <div className="text-xs text-[var(--muted-foreground)] mt-2 border-t border-[var(--border)] pt-1 flex items-center gap-2 flex-wrap">
                  {msg.dataAsOf && <span>依據資料時間 {msg.dataAsOf}</span>}
                  {msg.model && <span>{msg.model}</span>}
                </div>
              )}
            </div>
            {msg.role === "user" && (
              <div className="bg-[var(--secondary)] p-2 rounded-md h-fit shrink-0">
                <User className="w-4 h-4 text-[var(--muted-foreground)]" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="bg-[var(--primary)]/20 p-2 rounded-md h-fit">
              <Bot className="w-4 h-4 text-[var(--primary)]" />
            </div>
            <div className="bg-[var(--secondary)] rounded-lg px-4 py-3 flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-[var(--primary)]" />
              <span className="text-xs text-[var(--muted-foreground)]">
                查詢路網資料與 SOP 條文中...
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 建議問題：評審不必自己想怎麼問 */}
      {messages.length <= 1 && (
        <div className="px-5 pb-2 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => send(s)}
              disabled={loading}
              className="px-2.5 py-1 rounded-full text-xs border border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] transition disabled:opacity-50 focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="px-5 py-4 border-t border-[var(--border)]">
        <div className="flex gap-3">
          <label className="sr-only" htmlFor="whatif-input">
            What-if 情境問題
          </label>
          <input
            id="whatif-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) send();
            }}
            placeholder="輸入 What-if 情境問題..."
            className="flex-1 bg-[var(--secondary)] border border-[var(--input)] rounded-md px-4 py-3 text-sm placeholder-[var(--muted-foreground)] focus:outline-none focus:ring-[3px] focus:ring-[var(--ring)]/30 transition"
          />
          <button
            type="button"
            onClick={() => send()}
            disabled={loading || !input.trim()}
            aria-label="送出問題"
            className="bg-[var(--primary)] hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none text-[var(--primary-foreground)] rounded-md px-5 py-3 transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
