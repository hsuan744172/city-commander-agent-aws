import { useState } from "react";
import { ChevronDown, ChevronUp, Route, Clock, Copy, Check, AlertTriangle } from "lucide-react";
import { cn } from "../lib/utils";
import CMSInline from "./CMSInline";

export default function AdvisoryCard({ advisory, isSelected, onSelect }) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (advisory.error) {
    const isApiError = advisory.error.includes("API") || advisory.error.includes("http") || advisory.error.includes("503");
    return (
      <div className={cn(
        "rounded-lg p-4 border cursor-pointer transition",
        isSelected ? "border-[var(--primary)] bg-[var(--primary)]/5" : "border-[var(--border)] bg-[var(--card)] hover:bg-[var(--accent)]"
      )} onClick={onSelect}>
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-[var(--status-warning)]" />
          <span className="text-sm text-[var(--status-warning)]">
            {isApiError ? "AI 顧問忙碌中，已切換至 SOP 備援模式" : `${advisory.event_id} 處理異常`}
          </span>
        </div>
      </div>
    );
  }

  const eid = advisory.event_identification || {};
  const traffic = advisory.traffic_classification || {};
  const route = advisory.route_advisory || {};
  const ete = route.ete_estimate;
  const primary = route.primary_evacuation_route;
  const comms = advisory.public_communications || {};
  const special = advisory.special_advisory;

  const handleCopy = () => {
    const text = advisory.ai_narrative || advisory.summary || "";
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div
      className={cn(
        "rounded-lg border transition cursor-pointer",
        isSelected
          ? "border-[var(--primary)] ring-2 ring-[var(--ring)]/30 bg-[var(--primary)]/5"
          : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--muted-foreground)]/30"
      )}
      onClick={onSelect}
    >
      {/* Top summary */}
      <div className="p-4">
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <span className="text-sm font-bold">{advisory.event_id}</span>
          <SeverityBadge severity={eid.severity} />
          <LevelBadge level={traffic.max_level} />
          {eid.triggered_sop_articles?.map((s, i) => (
            <span key={i} className="text-[10px] px-1.5 py-0.5 bg-[var(--status-warning)]/20 text-[var(--status-warning)] rounded-sm font-medium">
              SOP {s.sop_number}
            </span>
          ))}
        </div>

        <div className="text-sm text-[var(--muted-foreground)] mb-3">{eid.location || eid.affected_segment}</div>

        <div className="flex items-center gap-4 flex-wrap">
          {primary && (
            <div className="flex items-center gap-1.5">
              <Route className="w-4 h-4 text-[var(--status-success)]" />
              <span className="text-sm font-medium text-[var(--status-success)]">{primary.primary_route_name}</span>
            </div>
          )}

          {ete && (
            <div className="flex items-center gap-1.5">
              <Clock className="w-4 h-4 text-[var(--status-info)]" />
              <span className="text-xl font-bold text-[var(--status-info)]">{ete.ete_minutes}</span>
              <span className="text-xs text-[var(--status-info)]">分鐘</span>
            </div>
          )}

          {special && !primary && (
            <span className="text-sm text-[var(--status-running)] font-medium">{special.title}</span>
          )}
        </div>

        <div className="flex items-center gap-2 mt-3">
          <button
            onClick={(e) => { e.stopPropagation(); handleCopy(); }}
            className="flex items-center gap-1 px-3 py-1.5 bg-[var(--secondary)] hover:bg-[var(--accent)] rounded-md text-xs text-[var(--muted-foreground)] transition"
          >
            {copied ? <Check className="w-3 h-3 text-[var(--status-success)]" /> : <Copy className="w-3 h-3" />}
            {copied ? "已複製" : "複製建議書"}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setDetailOpen(!detailOpen); }}
            className="flex items-center gap-1 px-3 py-1.5 bg-[var(--secondary)] hover:bg-[var(--accent)] rounded-md text-xs text-[var(--muted-foreground)] transition"
          >
            {detailOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {detailOpen ? "收合詳情" : "展開詳情"}
          </button>
        </div>
      </div>

      {/* Accordion detail */}
      {detailOpen && (
        <div className="border-t border-[var(--border)] px-4 pb-4 pt-3 space-y-3" onClick={(e) => e.stopPropagation()}>
          {advisory.ai_narrative && (
            <div className="bg-[var(--primary)]/10 rounded-md p-3">
              <div className="text-[10px] font-semibold text-[var(--primary)] mb-1">AI 決策分析</div>
              <div className="text-sm whitespace-pre-wrap leading-relaxed">{advisory.ai_narrative}</div>
            </div>
          )}

          {traffic.congestion_details?.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-[var(--muted-foreground)] mb-1">交通分級依據</div>
              {traffic.congestion_details.map((c, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="text-[var(--muted-foreground)]">{c.road_name}</span>
                  <span className={cn(
                    "font-bold",
                    c.level === "A" ? "text-[var(--status-error)]" : c.level === "B" ? "text-[var(--status-warning)]" : "text-[var(--status-success)]"
                  )}>
                    {Math.round(c.saturation_score * 100)}% {c.description}
                  </span>
                </div>
              ))}
            </div>
          )}

          {primary?.selection_reason && (
            <div>
              <div className="text-[10px] font-semibold text-[var(--muted-foreground)] mb-1">路徑選擇依據</div>
              <div className="text-sm text-[var(--muted-foreground)]">{primary.selection_reason}</div>
              {primary.secondary_routes?.length > 0 && (
                <div className="text-xs text-[var(--muted-foreground)] mt-1">
                  次要替代：{primary.secondary_routes.map(r => `${r.name}(${Math.round(r.saturation_score*100)}%)`).join("、")}
                </div>
              )}
            </div>
          )}

          {special?.actions && (
            <div>
              <div className="text-[10px] font-semibold text-[var(--muted-foreground)] mb-1">{special.title}</div>
              <ul className="text-sm text-[var(--muted-foreground)] space-y-0.5">
                {special.actions.map((a, i) => <li key={i}>• {a}</li>)}
              </ul>
            </div>
          )}

          {route.signal_adjustments?.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-[var(--muted-foreground)] mb-1">號誌調整</div>
              {route.signal_adjustments.map((s, i) => (
                <div key={i} className="text-sm text-[var(--muted-foreground)]">{s.road_name}：{s.action}</div>
              ))}
            </div>
          )}

          <CMSInline comms={comms} eventId={advisory.event_id} />
        </div>
      )}
    </div>
  );
}

function SeverityBadge({ severity }) {
  const styles = {
    Critical: "bg-[var(--status-error)] text-[var(--primary-foreground)]",
    High: "bg-[var(--status-warning)] text-[var(--primary-foreground)]",
    Medium: "bg-[var(--status-idle)] text-[var(--primary-foreground)]",
  };
  return severity ? (
    <span className={cn("text-xs rounded-sm font-bold px-2 py-0.5", styles[severity] || "bg-[var(--secondary)] text-[var(--muted-foreground)]")}>
      {severity}
    </span>
  ) : null;
}

function LevelBadge({ level }) {
  const styles = {
    A: "bg-[var(--status-error)]/20 text-[var(--status-error)] border border-[var(--status-error)]/30",
    B: "bg-[var(--status-warning)]/20 text-[var(--status-warning)] border border-[var(--status-warning)]/30",
    Normal: "bg-[var(--status-success)]/20 text-[var(--status-success)] border border-[var(--status-success)]/30",
  };
  const labels = { A: "A 級", B: "B 級", Normal: "正常" };
  return <span className={cn("text-[10px] px-1.5 py-0.5 rounded-sm font-medium", styles[level] || styles.Normal)}>{labels[level] || "正常"}</span>;
}
