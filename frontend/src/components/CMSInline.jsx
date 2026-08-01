import { useState } from "react";
import { Check, Copy, Globe, Languages, MonitorSmartphone, Send, Smartphone } from "lucide-react";
import { cn } from "../lib/utils";

const LANG_META = {
  "zh-TW": { flag: "🇹🇼", name: "繁體中文" },
  en: { flag: "🇺🇸", name: "English" },
  ja: { flag: "🇯🇵", name: "日本語" },
  ko: { flag: "🇰🇷", name: "한국어" },
};

const CHANNELS = [
  { id: "cms", label: "CMS 電子看板", icon: MonitorSmartphone, field: "content" },
  { id: "sms", label: "民眾簡訊", icon: Smartphone, field: "sms" },
];

const REQUIREMENT_ORDER = ["事故位置", "改道指引", "預計延誤時間", "求援或避開提醒"];

/**
 * 公眾通報
 *
 * 兩種通路分開呈現：
 *   CMS 看板  — SOP 第 2 條 (b) / 第 5 條明訂句式，逐字不改，適合看板字數
 *   民眾簡訊  — 交付要求的四項要點（事故位置、改道指引、預計延誤時間、求援或避開提醒）
 */
export default function CMSInline({ comms, eventId }) {
  const [activeLang, setActiveLang] = useState("zh-TW");
  const [channel, setChannel] = useState("cms");
  const [published, setPublished] = useState(new Set());
  const [copied, setCopied] = useState(null);

  const messages = comms?.cms_broadcast?.messages || [];
  const triggerSop6 = comms?.trigger_sop6_multilingual || false;
  const requirements = comms?.message_requirements || {};

  if (messages.length === 0) return null;

  const byLang = {};
  for (const m of messages) byLang[m.language] = m;
  const langs = Object.keys(byLang);
  const current = byLang[activeLang] || byLang[langs[0]];
  const activeChannel = CHANNELS.find((c) => c.id === channel) || CHANNELS[0];
  const text = current?.[activeChannel.field] || current?.content || "";
  const publishKey = `${activeLang}:${channel}`;

  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(publishKey);
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <div className="pt-4 border-t border-[var(--border)]">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Globe className="w-4 h-4 text-[var(--chart-5)]" />
        <span className="text-xs font-semibold text-[var(--chart-5)]">公眾通報</span>
        {triggerSop6 ? (
          <span className="flex items-center gap-1 bg-[var(--chart-5)]/20 px-2 py-0.5 rounded-sm text-[10px] text-[var(--chart-5)]">
            <Languages className="w-3 h-3" />
            SOP 第 6 條觸發，須多語發布
          </span>
        ) : (
          <span className="text-[10px] text-[var(--muted-foreground)]">
            未觸發 SOP 第 6 條，僅需繁體中文
          </span>
        )}
      </div>

      {/* 訊息要點檢核：交付要求的四項 */}
      {Object.keys(requirements).length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 mb-3">
          {REQUIREMENT_ORDER.filter((key) => key in requirements).map((key) => (
            <span
              key={key}
              className={cn(
                "flex items-center gap-1 text-[10px]",
                requirements[key]
                  ? "text-[var(--status-success)]"
                  : "text-[var(--status-warning)]",
              )}
            >
              {requirements[key] ? <Check className="w-3 h-3" /> : <span>—</span>}
              {key}
            </span>
          ))}
        </div>
      )}

      {/* 通路切換 */}
      <div className="flex gap-1 mb-2" role="tablist" aria-label="通報通路">
        {CHANNELS.map((c) => {
          const Icon = c.icon;
          const active = channel === c.id;
          return (
            <button
              key={c.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setChannel(c.id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                active
                  ? "bg-[var(--secondary)] text-[var(--foreground)] font-medium"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]",
              )}
            >
              <Icon className="w-3 h-3" />
              {c.label}
            </button>
          );
        })}
      </div>

      {/* 語言切換 */}
      {langs.length > 1 && (
        <div className="flex gap-1 mb-3 flex-wrap" role="tablist" aria-label="通報語言">
          {langs.map((lang) => {
            const meta = LANG_META[lang] || { flag: "🌐", name: lang };
            const active = activeLang === lang;
            const isPub = published.has(`${lang}:${channel}`);
            return (
              <button
                key={lang}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setActiveLang(lang)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                  active
                    ? "bg-[var(--chart-5)]/20 text-[var(--chart-5)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--accent)]",
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

      {text && (
        <div
          className={cn(
            "rounded-md p-4",
            published.has(publishKey) ? "bg-[var(--status-success)]/10" : "bg-[var(--secondary)]",
          )}
        >
          <p className="text-sm leading-relaxed mb-1">{text}</p>
          <div className="text-[10px] text-[var(--muted-foreground)] mb-3">
            {text.length} 字
            {channel === "cms" && "（依 SOP 明訂句式，逐字不改）"}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => setPublished(new Set([...published, publishKey]))}
              disabled={published.has(publishKey)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                published.has(publishKey)
                  ? "bg-[var(--status-success)]/20 text-[var(--status-success)]"
                  : "bg-[var(--chart-5)] hover:opacity-90 text-[var(--primary-foreground)]",
              )}
            >
              {published.has(publishKey) ? <Check className="w-3 h-3" /> : <Send className="w-3 h-3" />}
              {published.has(publishKey) ? "已標記發布" : `發布至${activeChannel.label}`}
            </button>
            <button
              type="button"
              onClick={copy}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent)] hover:bg-[var(--border)] rounded-md text-xs text-[var(--muted-foreground)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
            >
              {copied === publishKey ? (
                <Check className="w-3 h-3 text-[var(--status-success)]" />
              ) : (
                <Copy className="w-3 h-3" />
              )}
              {copied === publishKey ? "已複製" : "複製"}
            </button>
            <span className="text-[10px] text-[var(--muted-foreground)]">
              本 Demo 未串接實際發布通道，發布為狀態標記
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
