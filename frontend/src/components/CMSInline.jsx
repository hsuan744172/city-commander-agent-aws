import { useEffect, useMemo, useState } from "react";
import {
  Check,
  Copy,
  Globe,
  Languages,
  MonitorSmartphone,
  Send,
  Smartphone,
} from "lucide-react";
import { cn } from "../lib/utils";

const LANG_META = {
  "zh-TW": { code: "ZH", name: "繁體中文" },
  en: { code: "EN", name: "English" },
  ja: { code: "JA", name: "日本語" },
  ko: { code: "KO", name: "한국어" },
};

const CHANNELS = [
  { id: "cms", label: "CMS 電子看板", shortLabel: "CMS", icon: MonitorSmartphone, field: "content" },
  { id: "sms", label: "民眾簡訊", shortLabel: "SMS", icon: Smartphone, field: "sms" },
];

const REQUIREMENT_ORDER = ["事故位置", "改道指引", "預計延誤時間", "求援或避開提醒"];

export default function CMSInline({ comms, eventId }) {
  const messages = comms?.cms_broadcast?.messages || [];
  const byLang = useMemo(
    () => Object.fromEntries(messages.map((message) => [message.language, message])),
    [messages],
  );
  const langs = Object.keys(byLang);
  const [activeLang, setActiveLang] = useState(langs[0] || "zh-TW");
  const [channel, setChannel] = useState("cms");
  const [publicationState, setPublicationState] = useState({});
  const [copied, setCopied] = useState(null);

  useEffect(() => {
    setActiveLang((current) => (byLang[current] ? current : langs[0] || "zh-TW"));
    setChannel("cms");
    setPublicationState({});
  }, [eventId]); // 每個事件各自追蹤語言與通路，切換報告時不沿用舊狀態。

  if (messages.length === 0) return null;

  const triggerSop6 = Boolean(
    comms?.trigger_multilingual_sop6 ?? comms?.cms_broadcast?.trigger_sop6_multilingual,
  );
  const requirements = comms?.message_requirements || {};
  const currentLang = byLang[activeLang] ? activeLang : langs[0];
  const current = byLang[currentLang];
  const activeChannel = CHANNELS.find((item) => item.id === channel) || CHANNELS[0];
  const text = current?.[activeChannel.field] || current?.content || "";
  const publishKey = `${currentLang}:${channel}`;
  const combinations = langs.flatMap((lang) =>
    CHANNELS.map((item) => ({ key: `${lang}:${item.id}`, lang, channel: item })),
  );
  const publishedCount = combinations.filter(({ key }) => publicationState[key] === "published").length;
  const allPublished = combinations.length > 0 && publishedCount === combinations.length;

  const markPublished = (keys) => {
    const publishedAt = new Date().toLocaleTimeString("zh-TW", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    setPublicationState((currentState) => {
      const next = { ...currentState };
      keys.forEach((key) => {
        next[key] = "published";
        next[`${key}:time`] = publishedAt;
      });
      return next;
    });
  };

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(publishKey);
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <section className="pt-4 border-t border-[var(--border)]" aria-label="公眾通報發布台">
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <Globe className="w-4 h-4 text-[var(--chart-5)]" />
          <span className="text-sm font-semibold">公眾通報發布台</span>
          {triggerSop6 ? (
            <span className="flex items-center gap-1 bg-[var(--chart-5)]/20 px-2 py-0.5 rounded-sm text-xs text-[var(--chart-5)]">
              <Languages className="w-3 h-3" />
              SOP 第 6 條：四語發布
            </span>
          ) : (
            <span className="text-xs text-[var(--muted-foreground)]">僅需繁體中文</span>
          )}
          <span className="rounded-sm border border-[var(--status-info)]/30 bg-[var(--status-info)]/10 px-2 py-0.5 text-xs text-[var(--status-info)]">
            模擬發布
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--muted-foreground)]">
            {publishedCount}/{combinations.length} 通路完成
          </span>
          <button
            type="button"
            onClick={() => markPublished(combinations.map(({ key }) => key))}
            disabled={allPublished}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90 transition disabled:opacity-50 disabled:pointer-events-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            <Send className="w-3 h-3" />
            {allPublished ? "全通路已發布" : "一鍵發布全部"}
          </button>
        </div>
      </div>

      <div className="grid gap-1.5 mb-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="語言與通路發布狀態">
        {combinations.map(({ key, lang, channel: channelMeta }) => {
          const published = publicationState[key] === "published";
          const meta = LANG_META[lang] || { code: lang.toUpperCase(), name: lang };
          return (
            <button
              key={key}
              type="button"
              onClick={() => {
                setActiveLang(lang);
                setChannel(channelMeta.id);
              }}
              className={cn(
                "flex items-center justify-between gap-2 rounded-sm border px-2.5 py-2 text-xs transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                currentLang === lang && channel === channelMeta.id
                  ? "border-[var(--primary)] bg-[var(--primary)]/10"
                  : "border-[var(--border)] bg-[var(--background)] hover:bg-[var(--accent)]/50",
              )}
            >
              <span className="flex items-center gap-1.5">
                <span className="font-mono text-[var(--muted-foreground)]">{meta.code}</span>
                <span>{channelMeta.shortLabel}</span>
              </span>
              <span
                className={cn(
                  "flex items-center gap-1",
                  published ? "text-[var(--status-success)]" : "text-[var(--muted-foreground)]",
                )}
              >
                {published && <Check className="w-3 h-3" />}
                {published ? "已發布" : "待發布"}
              </span>
            </button>
          );
        })}
      </div>

      {Object.keys(requirements).length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 mb-3">
          {REQUIREMENT_ORDER.filter((key) => key in requirements).map((key) => (
            <span
              key={key}
              className={cn(
                "flex items-center gap-1 text-xs",
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

      <div className="flex gap-1 mb-2" role="tablist" aria-label="通報通路">
        {CHANNELS.map((item) => {
          const Icon = item.icon;
          const active = channel === item.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setChannel(item.id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                active
                  ? "bg-[var(--secondary)] text-[var(--foreground)] font-medium"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50",
              )}
            >
              <Icon className="w-3 h-3" />
              {item.label}
            </button>
          );
        })}
      </div>

      {langs.length > 1 && (
        <div className="flex gap-1 mb-3 flex-wrap" role="tablist" aria-label="通報語言">
          {langs.map((lang) => {
            const meta = LANG_META[lang] || { code: lang.toUpperCase(), name: lang };
            const active = currentLang === lang;
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
                    : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50",
                )}
              >
                <span className="font-mono">{meta.code}</span>
                <span>{meta.name}</span>
              </button>
            );
          })}
        </div>
      )}

      {text && (
        <div
          className={cn(
            "rounded-md p-4",
            publicationState[publishKey] === "published"
              ? "bg-[var(--status-success)]/10"
              : "bg-[var(--secondary)]",
          )}
        >
          <p className="text-sm leading-relaxed mb-1">{text}</p>
          <div className="text-xs text-[var(--muted-foreground)] mb-3">
            {text.length} 字{channel === "cms" && "（依 SOP 明訂句式）"}
            {publicationState[`${publishKey}:time`] &&
              ` · ${publicationState[`${publishKey}:time`]} 模擬發布`}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => markPublished([publishKey])}
              disabled={publicationState[publishKey] === "published"}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
                publicationState[publishKey] === "published"
                  ? "bg-[var(--status-success)]/20 text-[var(--status-success)]"
                  : "bg-[var(--chart-5)] text-[var(--primary-foreground)] hover:opacity-90",
              )}
            >
              {publicationState[publishKey] === "published" ? (
                <Check className="w-3 h-3" />
              ) : (
                <Send className="w-3 h-3" />
              )}
              {publicationState[publishKey] === "published"
                ? "已模擬發布"
                : `發布至${activeChannel.label}`}
            </button>
            <button
              type="button"
              onClick={copy}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent)]/50 hover:bg-[var(--accent)] rounded-md text-xs text-[var(--accent-foreground)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
            >
              {copied === publishKey ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied === publishKey ? "已複製" : "複製"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
