import { Globe, Send, Copy, Check, Languages, Bell } from "lucide-react";
import { useState, useCallback } from "react";

const LANG_META = {
  "zh-TW": { flag: "🇹🇼", name: "繁體中文", priority: 0 },
  en: { flag: "🇺🇸", name: "English", priority: 1 },
  ja: { flag: "🇯🇵", name: "日本語", priority: 2 },
  ko: { flag: "🇰🇷", name: "한국어", priority: 3 },
};

function Toast({ message, onDone }) {
  useState(() => {
    const t = setTimeout(onDone, 2000);
    return () => clearTimeout(t);
  });
  return (
    <div className="fixed bottom-6 right-6 bg-green-600 text-white px-4 py-2 rounded-lg shadow-lg text-sm flex items-center gap-2 animate-bounce z-50">
      <Check className="w-4 h-4" />
      {message}
    </div>
  );
}

export default function CMSPanel({ report }) {
  const [activeTab, setActiveTab] = useState("zh-TW");
  const [publishedLangs, setPublishedLangs] = useState(new Set());
  const [toast, setToast] = useState(null);

  if (!report?.advisories?.length) return null;

  // 收集所有通報
  const msgsByLang = {};
  let triggerSop6 = false;

  for (const adv of report.advisories) {
    const comms = adv.public_communications;
    if (!comms) continue;
    if (comms.trigger_multilingual_sop6) triggerSop6 = true;
    for (const msg of comms.broadcast_messages || []) {
      if (!msgsByLang[msg.language]) msgsByLang[msg.language] = [];
      msgsByLang[msg.language].push(msg);
    }
  }

  const availableLangs = Object.keys(msgsByLang).sort(
    (a, b) => (LANG_META[a]?.priority ?? 99) - (LANG_META[b]?.priority ?? 99)
  );

  if (availableLangs.length === 0) return null;

  const handleCopy = useCallback((text, lang) => {
    navigator.clipboard.writeText(text);
    setToast(`${LANG_META[lang]?.name || lang} 訊息已複製`);
  }, []);

  const handlePublish = useCallback((lang) => {
    setPublishedLangs((prev) => new Set([...prev, lang]));
    setToast(`${LANG_META[lang]?.name || lang} 已發布至 CMS`);
  }, []);

  const handlePublishAll = useCallback(() => {
    setPublishedLangs(new Set(availableLangs));
    setToast("全部語系已發布至 CMS 與簡訊系統");
  }, [availableLangs]);

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Globe className="w-5 h-5 text-purple-400" />
          <h2 className="text-sm font-semibold text-gray-200">
            模組五：多語化通報
          </h2>
          {triggerSop6 && (
            <span className="flex items-center gap-1 bg-purple-600/80 px-2 py-0.5 rounded text-xs font-bold">
              <Languages className="w-3 h-3" />
              SOP 6 多語觸發
            </span>
          )}
        </div>
        <button
          onClick={handlePublishAll}
          disabled={publishedLangs.size === availableLangs.length}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:bg-green-700 disabled:text-green-200 rounded-lg text-xs font-medium transition"
        >
          <Bell className="w-3.5 h-3.5" />
          {publishedLangs.size === availableLangs.length ? "全部已發布" : "一鍵全部發布"}
        </button>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 mb-4 border-b border-gray-800 pb-2 overflow-x-auto">
        {availableLangs.map((lang) => {
          const meta = LANG_META[lang] || { flag: "🌐", name: lang };
          const isActive = activeTab === lang;
          const isPublished = publishedLangs.has(lang);
          return (
            <button
              key={lang}
              onClick={() => setActiveTab(lang)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t-lg text-xs font-medium transition whitespace-nowrap ${
                isActive
                  ? "bg-gray-800 text-white border-b-2 border-purple-400"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
              }`}
            >
              <span>{meta.flag}</span>
              <span>{meta.name}</span>
              {isPublished && <Check className="w-3 h-3 text-green-400" />}
            </button>
          );
        })}
      </div>

      {/* Active Tab Content */}
      <div className="space-y-3">
        {(msgsByLang[activeTab] || []).map((msg, idx) => {
          const meta = LANG_META[activeTab] || { flag: "🌐", name: activeTab };
          const isPublished = publishedLangs.has(activeTab);

          return (
            <div
              key={idx}
              className={`rounded-lg p-4 border transition ${
                isPublished
                  ? "bg-green-900/20 border-green-700"
                  : "bg-gray-800 border-gray-700"
              }`}
            >
              {/* Card Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-lg">{meta.flag}</span>
                  <span className="text-xs font-medium text-gray-300">{meta.name}</span>
                  {triggerSop6 && (
                    <span className="text-xs bg-purple-800/50 text-purple-200 px-1.5 py-0.5 rounded">
                      優先發送
                    </span>
                  )}
                </div>
                <span className="text-xs text-gray-500">{msg.template_used}</span>
              </div>

              {/* Message Content */}
              <p className="text-sm text-gray-100 leading-relaxed bg-gray-900/50 rounded p-3 my-2">
                {msg.message}
              </p>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 mt-3">
                <button
                  onClick={() => handlePublish(activeTab)}
                  disabled={isPublished}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition ${
                    isPublished
                      ? "bg-green-700 text-green-200 cursor-default"
                      : "bg-purple-600 hover:bg-purple-500 text-white"
                  }`}
                >
                  {isPublished ? <Check className="w-3.5 h-3.5" /> : <Send className="w-3.5 h-3.5" />}
                  {isPublished ? "已發布" : "發布 CMS"}
                </button>
                <button
                  onClick={() => handleCopy(msg.message, activeTab)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs font-medium text-gray-200 transition"
                >
                  <Copy className="w-3.5 h-3.5" />
                  複製
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
