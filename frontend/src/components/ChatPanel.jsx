import { useState, useRef, useEffect } from "react";
import { Send, Loader2, Bot, User, Sparkles } from "lucide-react";
import { cn } from "../lib/utils";

export default function ChatPanel() {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "我是城市應變指揮官 AI 策略顧問。\n\n您可以向我提出任何 What-if 假設情境，例如：\n• 若 BL17 人數增至 40,000 人怎麼辦？\n• 忠孝東路與光復南路同時癱瘓的應變策略？\n• 如果號誌故障同時發生人潮推擠？\n\n我將依據 SOP 條款為您提供決策建議。" },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const prompt = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: prompt }]);
    setLoading(true);

    try {
      const res = await fetch("/api/what-if", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await res.json();
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: data.response,
        model: data.model,
      }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: "assistant", content: `連線錯誤：${e.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] flex flex-col h-[calc(100vh-140px)] shadow-sm">
      {/* Header */}
      <div className="px-5 py-4 border-b border-[var(--border)] flex items-center gap-2">
        <Sparkles className="w-5 h-5 text-[var(--primary)]" />
        <span className="text-sm font-semibold">AI 策略顧問 — What-if 情境分析</span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {messages.map((msg, idx) => (
          <div key={idx} className={cn("flex gap-3", msg.role === "user" && "justify-end")}>
            {msg.role === "assistant" && (
              <div className="bg-[var(--primary)]/20 p-2 rounded-md h-fit">
                <Bot className="w-4 h-4 text-[var(--primary)]" />
              </div>
            )}
            <div className={cn(
              "max-w-[80%] rounded-lg px-4 py-3",
              msg.role === "user"
                ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                : "bg-[var(--secondary)] text-[var(--foreground)]"
            )}>
              <div className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</div>
              {msg.model && (
                <div className="text-xs text-[var(--muted-foreground)] mt-2 border-t border-[var(--border)] pt-1">
                  {msg.model}
                </div>
              )}
            </div>
            {msg.role === "user" && (
              <div className="bg-[var(--secondary)] p-2 rounded-md h-fit">
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
            <div className="bg-[var(--secondary)] rounded-lg px-4 py-3">
              <Loader2 className="w-4 h-4 animate-spin text-[var(--primary)]" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-5 py-4 border-t border-[var(--border)]">
        <div className="flex gap-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            placeholder="輸入 What-if 情境問題..."
            className="flex-1 bg-[var(--secondary)] border border-[var(--input)] rounded-md px-4 py-3 text-sm placeholder-[var(--muted-foreground)] focus:outline-none focus:ring-[3px] focus:ring-[var(--ring)]/30 transition"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="bg-[var(--primary)] hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none text-[var(--primary-foreground)] rounded-md px-5 py-3 transition"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
