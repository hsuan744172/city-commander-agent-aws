import { useState } from "react";
import { Globe, Send, Copy, Check, Languages } from "lucide-react";

const LANG_META = {
  "zh-TW": { flag: "🇹🇼", name: "繁體中文" },
  en: { flag: "🇺🇸", name: "English" },
  ja: { flag: "🇯🇵", name: "日本語" },
  ko: { flag: "🇰🇷", name: "한국어" },
};

export default function CMSInline({ comms, eventId }) {
  const [published, setPublished] = useState(new Set());
  const [copied, setCopied] = useState(null);

  const messages = comms?.broadcast_messages || [];
  const triggerSop6 = comms?.trigger_sop6_multilingual || false;

  if (messages.length === 0) return null;

  const handleCopy = (text, lang) => {
    navigator.clipboard.writeText(text);
    setCopied(lang);
    setTimeout(() => setCopied(null), 1500);
  };

  const handlePublish = (lang) => {
    setPublished((prev) => new Set([...prev, lang]));
  };

  return (
    <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <Globe className="w-4 h-4 text-purple-400" />
        <span className="text-xs font-semibold text-purple-300">
          公眾通報
        </span>
        {triggerSop6 && (
          <span className="flex items-center gap-1 bg-purple-600/60 px-2 py-0.5 rounded text-xs">
            <Languages className="w-3 h-3" />
            SOP 第 6 條觸發・多語發布
          </span>
        )}
      </div>

      <div className="space-y-2">
        {messages.map((msg, idx) => {
          const meta = LANG_META[msg.language] || { flag: "🌐", name: msg.language };
          const isPub = published.has(msg.language);
          const isCopied = copied === msg.language;

          return (
            <div key={idx} className={`rounded-lg p-3 border ${isPub ? "bg-green-900/20 border-green-800/50" : "bg-gray-900/50 border-gray-700/50"}`}>
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <span>{meta.flag}</span>
                  <span className="text-xs font-medium text-gray-300">{meta.name}</span>
                </div>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => handleCopy(msg.message, msg.language)}
                    className="flex items-center gap-1 px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs transition"
                  >
                    {isCopied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
                    {isCopied ? "已複製" : "複製"}
                  </button>
                  <button
                    onClick={() => handlePublish(msg.language)}
                    disabled={isPub}
                    className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition ${isPub ? "bg-green-700 text-green-200" : "bg-purple-600 hover:bg-purple-500"}`}
                  >
                    {isPub ? <Check className="w-3 h-3" /> : <Send className="w-3 h-3" />}
                    {isPub ? "已發布" : "發布"}
                  </button>
                </div>
              </div>
              <p className="text-sm text-gray-100 leading-relaxed">{msg.message}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
