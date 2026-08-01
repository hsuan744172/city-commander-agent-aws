import { useState } from "react";
import {
  AlertTriangle,
  Building2,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Copy,
  Route,
  ScrollText,
  Timer,
  TrafficCone,
  Users,
} from "lucide-react";
import { cn } from "../lib/utils";
import CMSInline from "./CMSInline";
import RouteCandidateTable from "./RouteCandidateTable";

export default function AdvisoryCard({
  advisory,
  isSelected,
  onSelect,
  defaultExpanded = false,
}) {
  const [detailOpen, setDetailOpen] = useState(defaultExpanded);
  const [copied, setCopied] = useState(false);

  if (advisory.error) {
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
          }
        }}
        className={cn(
          "rounded-lg p-4 border cursor-pointer transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]",
          isSelected
            ? "border-[var(--primary)] bg-[var(--primary)]/5"
            : "border-[var(--border)] bg-[var(--card)] hover:bg-[var(--accent)]",
        )}
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-[var(--status-warning)]" />
          <span className="text-sm text-[var(--status-warning)]">
            {advisory.event_id} 處理異常：{advisory.error}
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
  const analysis = route.route_analysis;
  const navigation = route.navigation_update || {};
  const comms = advisory.public_communications || {};
  const fieldActions = advisory.field_actions;
  const crossActions = advisory.cross_system_actions || [];
  const situational = advisory.situational_sop_articles || [];
  const clauses = advisory.sop_clauses || [];

  const eventActions = crossActions.filter((a) => a.scope !== "situational");
  const situationalActions = crossActions.filter((a) => a.scope === "situational");

  const handleCopy = () => {
    const lines = [
      `【交控中心建議書】${advisory.event_id}`,
      `分析時間：${advisory.analysis_time || advisory.generated_at}`,
      advisory.ai_narrative || advisory.summary || "",
    ];
    if (primary) {
      lines.push(
        "",
        `主疏散路徑：${primary.primary_route_name}（${primary.selection_reason}）`,
      );
    }
    if (ete) lines.push(`預計恢復時間：${ete.ete_minutes} 分鐘（${ete.formula}）`);
    if (crossActions.length) {
      lines.push("", "跨單位請求：");
      crossActions.forEach((a) => lines.push(`・[${a.sop_reference}] ${a.agency}：${a.request}`));
    }
    const messages = comms.broadcast_messages || [];
    if (messages.length) {
      lines.push("", "公眾通報：");
      messages.forEach((m) => lines.push(`・[${m.language}] ${m.sms_text || m.message}`));
    }
    navigator.clipboard.writeText(lines.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div
      className={cn(
        "rounded-lg border transition",
        isSelected
          ? "border-[var(--primary)] ring-2 ring-[var(--ring)]/30 bg-[var(--primary)]/5"
          : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--muted-foreground)]/30",
      )}
    >
      {/* Top summary */}
      <div
        role="button"
        tabIndex={0}
        aria-label={`選取事件 ${advisory.event_id}`}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
          }
        }}
        className="p-4 cursor-pointer focus-visible:outline-none focus-visible:ring-[var(--ring)] focus-visible:ring-[3px] rounded-lg"
      >
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <span className="text-sm font-bold">{advisory.event_id}</span>
          <SeverityBadge severity={eid.severity} />
          <LevelBadge level={traffic.max_level} />
          {eid.triggered_sop_articles?.map((s) => (
            <span
              key={s.sop_number}
              title={s.reason}
              className="text-[10px] px-1.5 py-0.5 bg-[var(--status-warning)]/20 text-[var(--status-warning)] rounded-sm font-medium"
            >
              SOP {s.sop_number}
            </span>
          ))}
          {advisory.elapsed_ms != null && (
            <span
              title="本事件端到端處理耗時"
              className="ml-auto flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]"
            >
              <Timer className="w-3 h-3" />
              {(advisory.elapsed_ms / 1000).toFixed(1)} 秒
            </span>
          )}
        </div>

        <div className="text-sm text-[var(--muted-foreground)] mb-1">
          {eid.location || eid.affected_segment}
        </div>

        {/* 人流事件經 affected_road 對應到車流路段時要講清楚，否則分級看起來沒來由 */}
        {eid.traffic_segment_source === "affected_road" && (
          <div className="text-xs text-[var(--muted-foreground)] mb-2">
            人流事件經 affected_road 對應車流路段 {eid.traffic_segment}，交通分級與 ETE 以該路段計算
          </div>
        )}

        <div className="flex items-center gap-4 flex-wrap">
          {primary && (
            <div className="flex items-center gap-1.5">
              <Route className="w-4 h-4 text-[var(--status-success)]" />
              <span className="text-sm font-medium text-[var(--status-success)]">
                {primary.primary_route_name}
              </span>
            </div>
          )}

          {ete && (
            <div className="flex items-center gap-1.5">
              <Clock className="w-4 h-4 text-[var(--status-info)]" />
              <span className="text-xl font-bold text-[var(--status-info)]">
                {ete.ete_minutes}
              </span>
              <span className="text-xs text-[var(--status-info)]">分鐘</span>
            </div>
          )}

          {navigation.status === "simulated_published" && (
            <span className="text-xs px-2 py-0.5 rounded-sm border border-[var(--status-info)]/30 bg-[var(--status-info)]/10 text-[var(--status-info)] font-medium">
              導航資訊已模擬發布
            </span>
          )}

          {comms.trigger_multilingual_sop6 && (
            <span className="text-xs px-2 py-0.5 rounded-sm bg-[var(--chart-5)]/20 text-[var(--chart-5)] font-medium">
              SOP 6 多語通報
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 mt-3">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              handleCopy();
            }}
            className="flex items-center gap-1 px-3 py-1.5 bg-[var(--secondary)] hover:bg-[var(--accent)] rounded-md text-xs text-[var(--muted-foreground)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            {copied ? (
              <Check className="w-3 h-3 text-[var(--status-success)]" />
            ) : (
              <Copy className="w-3 h-3" />
            )}
            {copied ? "已複製" : "複製建議書"}
          </button>
          <button
            type="button"
            aria-expanded={detailOpen}
            onClick={(e) => {
              e.stopPropagation();
              setDetailOpen(!detailOpen);
            }}
            className="flex items-center gap-1 px-3 py-1.5 bg-[var(--secondary)] hover:bg-[var(--accent)] rounded-md text-xs text-[var(--muted-foreground)] transition focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
          >
            {detailOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {detailOpen ? "收合詳情" : "展開詳情"}
          </button>
        </div>
      </div>

      {/* Accordion detail */}
      {detailOpen && (
        <div className="border-t border-[var(--border)] px-4 pb-4 pt-3 space-y-3">
          {advisory.ai_narrative && (
            <section className="bg-[var(--primary)]/10 rounded-md p-3">
              <div className="text-[10px] font-semibold text-[var(--primary)] mb-1 flex items-center gap-1.5">
                AI 決策分析
                {advisory.ai_narrative_source === "fallback" && (
                  <span className="text-[var(--status-warning)] font-normal">
                    （AI 未連線，以下為程式依 SOP 組出的敘述）
                  </span>
                )}
              </div>
              <div className="text-sm whitespace-pre-wrap leading-relaxed">
                {advisory.ai_narrative}
              </div>
            </section>
          )}

          {/* 交通分級：全 15 路段的數據佐證 */}
          {traffic.congestion_details?.length > 0 && (
            <Section title="交通分級判定依據">
              <div className="text-xs text-[var(--muted-foreground)] mb-1">
                事件路段 {traffic.incident_segment} 判定 {traffic.incident_segment_level}；
                全網最高 {traffic.network_max_level}；
                城市應變觸發路段最高 {traffic.trigger_max_level}
              </div>
              <div className="space-y-0.5 max-h-44 overflow-y-auto pr-1">
                {traffic.congestion_details.map((c) => (
                  <div key={c.segment_id} className="flex items-center justify-between text-sm gap-2">
                    <span className="text-[var(--muted-foreground)] truncate">
                      {c.road_name}
                      {c.is_trigger_segment && (
                        <span className="ml-1 text-[9px] px-1 rounded-sm bg-[var(--accent)] text-[var(--accent-foreground)]">
                          觸發
                        </span>
                      )}
                      {c.is_incident_segment && (
                        <span className="ml-1 text-[9px] px-1 rounded-sm bg-[var(--status-error)]/20 text-[var(--status-error)]">
                          事件
                        </span>
                      )}
                    </span>
                    <span
                      className={cn(
                        "font-bold shrink-0",
                        c.level === "A"
                          ? "text-[var(--status-error)]"
                          : c.level === "B"
                            ? "text-[var(--status-warning)]"
                            : "text-[var(--status-success)]",
                      )}
                    >
                      {Math.round(c.saturation_score * 100)}% {c.description}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* 替代路徑：選擇依據 + 次要 + 完整候選評估表 */}
          {primary?.selection_reason && (
            <Section title="替代路徑建議">
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
                {primary.selection_reason}
              </p>
              {primary.congestion_note && (
                <p className="text-xs text-[var(--status-warning)] mt-1">
                  {primary.congestion_note}
                </p>
              )}
              {primary.secondary_routes?.length > 0 && (
                <div className="text-xs text-[var(--muted-foreground)] mt-1">
                  次要疏散：
                  {primary.secondary_routes
                    .map((r) => `${r.name}（${Math.round((r.saturation_score || 0) * 100)}%）`)
                    .join("、")}
                </div>
              )}
              <RouteCandidateTable
                candidates={analysis?.candidates || primary.excluded_routes}
                upstream={analysis?.upstream_resolution}
              />
            </Section>
          )}

          {navigation.status === "simulated_published" && (
            <Section title="導航資訊更新">
              <div className="rounded-md border border-[var(--status-info)]/30 bg-[var(--status-info)]/10 p-3 text-sm">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="font-medium text-[var(--status-info)]">已模擬發布至導航服務</span>
                  <span className="text-xs text-[var(--muted-foreground)]">
                    發布時間 {navigation.published_at}
                  </span>
                </div>
                <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                  封閉 {navigation.closed_segment_name}；主疏散路徑 {navigation.primary_route?.name}
                  {navigation.secondary_routes?.length > 0 &&
                    `；次要疏散 ${navigation.secondary_routes.map((item) => item.name).join("、")}`}
                </div>
              </div>
            </Section>
          )}

          {/* ETE 計算分解 */}
          {ete && (
            <Section title="預計恢復時間計算">
              <p className="text-sm text-[var(--muted-foreground)] leading-relaxed">
                {ete.formula}
              </p>
              <div className="text-xs text-[var(--muted-foreground)] mt-1 space-y-0.5">
                <div>
                  嚴重度 {ete.severity} → 基礎清除 {ete.base_clearance_minutes} 分鐘；
                  壅塞懲罰 {ete.congestion_penalty_minutes} 分鐘
                  {ete.avg_saturation_score != null &&
                    `（受影響路段平均飽和度 ${Math.round(ete.avg_saturation_score * 100)}%）`}
                </div>
                <div>受影響路段定義：{ete.affected_segments_definition}</div>
                {ete.affected_segments?.length > 0 && (
                  <div>
                    納入計算：
                    {ete.affected_segments
                      .map((s) =>
                        s.available
                          ? `${s.road_name} ${Math.round(s.saturation_score * 100)}%`
                          : `${s.segment_id}（無車流資料）`,
                      )
                      .join("、")}
                  </div>
                )}
                {ete.note && <div className="text-[var(--status-warning)]">{ete.note}</div>}
              </div>
            </Section>
          )}

          {/* 現場處置 */}
          {fieldActions?.actions?.length > 0 && (
            <Section title={fieldActions.title}>
              <ul className="text-sm text-[var(--muted-foreground)] space-y-0.5">
                {fieldActions.actions.map((a, i) => (
                  <li key={i}>・{a}</li>
                ))}
              </ul>
            </Section>
          )}

          {/* 號誌調整（含時段） */}
          {route.signal_adjustments?.length > 0 && (
            <Section title="號誌調整建議" icon={TrafficCone}>
              {route.signal_adjustments.map((s, i) => (
                <div key={i} className="text-sm text-[var(--muted-foreground)]">
                  {s.road_name}：{s.action}
                  {s.window && (
                    <span className="block text-xs">時段：{s.window}</span>
                  )}
                </div>
              ))}
            </Section>
          )}

          {/* 跨系統聯動 */}
          {eventActions.length > 0 && (
            <Section title="跨系統聯動（本事件）" icon={Building2}>
              <ul className="space-y-1">
                {eventActions.map((a, i) => (
                  <li key={i} className="text-sm">
                    <span className="text-[10px] px-1 py-0.5 rounded-sm bg-[var(--secondary)] text-[var(--muted-foreground)] mr-1.5">
                      {a.sop_reference}
                    </span>
                    <span className="font-medium">{a.agency}</span>
                    <span className="text-[var(--muted-foreground)]">：{a.request}</span>
                    {a.basis && (
                      <span className="block text-xs text-[var(--muted-foreground)] ml-1">
                        依據：{a.basis}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/* 全市態勢：與本事件無因果關係的資料型條款 */}
          {(situational.length > 0 || situationalActions.length > 0) && (
            <Section title="同時段全市態勢（非本事件觸發）" icon={Users}>
              {situational.map((s) => (
                <div key={s.sop_number} className="text-sm mb-1">
                  <span className="font-medium">
                    SOP 第 {s.sop_number} 條 {s.title}
                  </span>
                  <span className="block text-xs text-[var(--muted-foreground)]">{s.reason}</span>
                </div>
              ))}
              {situationalActions.map((a, i) => (
                <div key={i} className="text-xs text-[var(--muted-foreground)]">
                  ・{a.agency}：{a.request}
                </div>
              ))}
            </Section>
          )}

          {/* SOP 第 6 條判定證據 */}
          {comms.roaming_trigger_stations?.length > 0 && (
            <Section title="SOP 第 6 條多語觸發依據">
              <p className="text-xs text-[var(--muted-foreground)] mb-1">
                判定範圍：{comms.roaming_scope || "全資料集所有基地台"}
              </p>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {comms.roaming_trigger_stations.map((s) => (
                  <span key={s.bs_id} className="text-sm">
                    {s.location_name}
                    <span className="ml-1 font-mono font-medium text-[var(--chart-5)]">
                      {s.roaming_user_pct_display}
                    </span>
                  </span>
                ))}
              </div>
            </Section>
          )}

          {/* SOP 條文原文 */}
          {clauses.length > 0 && (
            <details>
              <summary className="text-[10px] font-semibold text-[var(--muted-foreground)] cursor-pointer flex items-center gap-1.5">
                <ScrollText className="w-3 h-3" />
                引用之 SOP 條文原文（{clauses.length} 條）
              </summary>
              <div className="mt-2 space-y-2">
                {clauses.map((c) => (
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
        </div>
      )}

      <div className="px-4 pb-4">
        <CMSInline comms={comms} eventId={advisory.event_id} />
      </div>
    </div>
  );
}

function Section({ title, icon: Icon, children }) {
  return (
    <section>
      <div className="text-[10px] font-semibold text-[var(--muted-foreground)] mb-1 flex items-center gap-1.5">
        {Icon && <Icon className="w-3 h-3" />}
        {title}
      </div>
      {children}
    </section>
  );
}

function SeverityBadge({ severity }) {
  const styles = {
    Critical: "bg-[var(--status-error)] text-[var(--primary-foreground)]",
    High: "bg-[var(--status-warning)] text-[var(--primary-foreground)]",
    Medium: "bg-[var(--status-idle)] text-[var(--primary-foreground)]",
  };
  return severity ? (
    <span
      className={cn(
        "text-xs rounded-sm font-bold px-2 py-0.5",
        styles[severity] || "bg-[var(--secondary)] text-[var(--muted-foreground)]",
      )}
    >
      {severity}
    </span>
  ) : null;
}

function LevelBadge({ level }) {
  const styles = {
    A: "bg-[var(--status-error)]/20 text-[var(--status-error)] border border-[var(--status-error)]/30",
    B: "bg-[var(--status-warning)]/20 text-[var(--status-warning)] border border-[var(--status-warning)]/30",
    Normal:
      "bg-[var(--status-success)]/20 text-[var(--status-success)] border border-[var(--status-success)]/30",
  };
  const labels = { A: "A 級", B: "B 級", Normal: "正常" };
  return (
    <span className={cn("text-[10px] px-1.5 py-0.5 rounded-sm font-medium", styles[level] || styles.Normal)}>
      {labels[level] || "正常"}
    </span>
  );
}
