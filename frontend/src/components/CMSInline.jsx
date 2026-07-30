import { useState } from "react";
import { Globe, Send, Copy, Check, Languages } from "lucide-react";

const LANG_META = {
  "zh-TW": { flag: "🇹🇼", name: "繁體中文" },
  en: { flag: "🇺🇸", name: "English" },
  ja: { flag: "🇯🇵", name: "日本語" },
  ko: { flag: "🇰🇷", name: "한국어" },
};

export default function CMSInline({ comms, eventId }) {
  const [activeTab, setActiveTab] = useState("zh-TW");
  const [published, setPublished] = useState(new Set());
  const [copied, setCopied] = useState(null);

  const messages = comms?.broadcast_messages || [];
  const triggerSop6 = comms?.trigger_sop6_multilingual || false;

  if (messages.length === 0) return null;

  const msgsByLang = {};
  for (const m of messages) {
    msgsByLang[m.language] = m;
  }
  const langs = Object.keys(msgsByLang);

  const handleCopy = (text, lang) => {
    navigator.clipboard.writeText(text);
    setCopied(lang);
    setTimeout(() => setCopied(null), 1500);
  };

  const currentMsg = msgsByLang[activeTab];

  return (
    <div className="pt-4 border-t border-gray-200">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <Globe className="w-4 h-4 text-purple-400" />
        <span className="text-xs font-semibold text-purple-600">公眾通報</span>
        {triggerSop6 && (
          <span className="flex items-center gap-1 bg-purple-600/40 px-2 py-0.5 rounded text-[10px] text-purple-700">
            <Languages className="w-3 h-3" />
            SOP 6 多語觸發
          </span>
        )}
      </div>

      {/* Tabs (only show if multi-language) */}
      {langs.length > 1 && (
        <div className="flex gap-1 mb-3">
          {langs.map((lang) => {
            const meta = LANG_META[lang] || { flag: "🌐", name: lang };
            const active = activeTab === lang;
            const isPub = published.has(lang);
            return (
              <button
                key={lang}
                onClick={() => setActiveTab(lang)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition ${
                  active ? "bg-purple-600/30 text-purple-700" : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
                }`}
              >
                <span>{meta.flag}</span>
                <span>{meta.name}</span>
                {isPub && <Check className="w-3 h-3 text-green-400" />}
              </button>
            );
          })}
        </div>
      )}

      {/* Active Message Card */}
      {currentMsg && (
        <div className={`rounded-lg p-4 ${published.has(activeTab) ? "bg-green-950/20" : "bg-gray-50"}`}>
          <p className="text-sm text-gray-800 leading-relaxed mb-3">{currentMsg.message}</p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => { setPublished(new Set([...published, activeTab])); }}
              disabled={published.has(activeTab)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                published.has(activeTab) ? "bg-green-700/50 text-green-600" : "bg-purple-600 hover:bg-purple-500 text-white"
              }`}
            >
              {published.has(activeTab) ? <Check className="w-3 h-3" /> : <Send className="w-3 h-3" />}
              {published.has(activeTab) ? "已發布" : "發布 CMS"}
            </button>
            <button
              onClick={() => handleCopy(currentMsg.message, activeTab)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-200 hover:bg-gray-300 rounded-lg text-xs text-gray-700 transition"
            >
              {copied === activeTab ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
              {copied === activeTab ? "已複製" : "複製"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
