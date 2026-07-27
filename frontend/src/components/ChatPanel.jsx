import { useState, useRef, useEffect } from "react";
import { MessageCircle, Send, Loader2, Bot, User } from "lucide-react";

export default function ChatPanel() {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "我是城市應變指揮官 AI 顧問。你可以問我 What-if 假設情境，例如：「若 BL17 人數增至 40,000 人怎麼辦？」" },
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
      setMessages((prev) => [...prev, { role: "assistant", content: data.response, model: data.model }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: "assistant", content: `連線錯誤：${e.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 flex flex-col h-[600px]">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center gap-2">
        <MessageCircle className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-semibold text-gray-200">AI 策略顧問</span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex gap-2 ${msg.role === "user" ? "justify-end" : ""}`}>
            {msg.role === "assistant" && <Bot className="w-5 h-5 text-blue-400 mt-1 shrink-0" />}
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${msg.role === "user" ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-200"}`}>
              <div className="whitespace-pre-wrap">{msg.content}</div>
              {msg.model && <div className="text-xs text-gray-500 mt-1">{msg.model}</div>}
            </div>
            {msg.role === "user" && <User className="w-5 h-5 text-gray-400 mt-1 shrink-0" />}
          </div>
        ))}
        {loading && (
          <div className="flex gap-2">
            <Bot className="w-5 h-5 text-blue-400 mt-1" />
            <div className="bg-gray-800 rounded-lg px-3 py-2"><Loader2 className="w-4 h-4 animate-spin text-blue-400" /></div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-gray-800">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="輸入 What-if 情境問題..."
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
          />
          <button onClick={handleSend} disabled={loading || !input.trim()} className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 rounded-lg px-3 py-2 transition">
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
