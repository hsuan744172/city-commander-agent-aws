import { useState } from "react";
import { Globe, Send, Copy, Check, Languages } from "lucide-react";
import { cn } from "../lib/utils";

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
    <div className="pt-4 border-t border-[var(--border)]">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <Globe className="w-4 h-4 text-[var(--chart-5)]" />
        <span className="text-xs font-semibold text-[var(--chart-5)]">公眾通報</span>
        {triggerSop6 && (
          <span className="flex items-center gap-1 bg-[var(--chart-5)]/20 px-2 py-0.5 rounded-sm text-[10px] text-[var(--chart-5)]">
            <Languages className="w-3 h-3" />
            SOP 6 多語觸發
          </span>
        )}
      </div>

      {/* Tabs */}
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
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition",
                  active
                    ? "bg-[var(--chart-5)]/20 text-[var(--chart-5)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--accent)]"
                )}
              >
                <span>{meta.flag}</span>
                <span>{meta.name}</span>
                {isPub && <Check className="w-3 h-3 text-[var(--status-success)]" />}
              </button>
            );
          })}
        </div>
      )}

      {/* Active Message Card */}
      {currentMsg && (
        <div className={cn(
          "rounded-md p-4",
          published.has(activeTab) ? "bg-[var(--status-success)]/10" : "bg-[var(--secondary)]"
        )}>
          <p className="text-sm leading-relaxed mb-3">{currentMsg.message}</p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => { setPublished(new Set([...published, activeTab])); }}
              disabled={published.has(activeTab)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition",
                published.has(activeTab)
                  ? "bg-[var(--status-success)]/20 text-[var(--status-success)]"
                  : "bg-[var(--chart-5)] hover:opacity-90 text-[var(--primary-foreground)]"
              )}
            >
              {published.has(activeTab) ? <Check className="w-3 h-3" /> : <Send className="w-3 h-3" />}
              {published.has(activeTab) ? "已發布" : "發布 CMS"}
            </button>
            <button
              onClick={() => handleCopy(currentMsg.message, activeTab)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent)] hover:bg-[var(--border)] rounded-md text-xs text-[var(--muted-foreground)] transition"
            >
              {copied === activeTab ? <Check className="w-3 h-3 text-[var(--status-success)]" /> : <Copy className="w-3 h-3" />}
              {copied === activeTab ? "已複製" : "複製"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
