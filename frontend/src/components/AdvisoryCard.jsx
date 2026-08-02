import { useState } from "react";
import {
  AlertTriangle,
  Bot,
  Brain,
  Building2,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  ListChecks,
  Navigation,
  Route,
  ScrollText,
  Timer,
  TrafficCone,
  Users,
} from "lucide-react";
import { cn } from "../lib/utils";
import CMSInline from "./CMSInline";
import RouteCandidateTable from "./RouteCandidateTable";
import DecisionTracePanel from "./DecisionTracePanel";
import SopConformancePanel from "./SopConformancePanel";
import AiReasoningTrace from "./AiReasoningTrace";
import { ENGINE_STYLES } from "../lib/aiLabels";
import { NARRATIVE_SOURCE_LABELS, trustStatement } from "../lib/explain";

const NARRATIVE_SOURCES = {
  ai_generated: { label: NARRATIVE_SOURCE_LABELS.ai_generated, tone: "info" },
  ai_generated_partial: {
    label: NARRATIVE_SOURCE_LABELS.ai_generated_partial,
    tone: "info",
  },
  fallback: { label: NARRATIVE_SOURCE_LABELS.fallback, tone: "warning" },
  deadline_fallback: {
    label: NARRATIVE_SOURCE_LABELS.deadline_fallback,
    tone: "warning",
  },
};

const TABS = [
  { id: "plan", label: "處置方案", icon: ListChecks },
  { id: "basis", label: "判定依據", icon: ScrollText },
  { id: "reasoning", label: "AI 推理", icon: Brain },
  { id: "clauses", label: "SOP 原文", icon: ScrollText },
];

function percent(value) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

/**
 * 交控中心建議書
 *
 * 版面刻意做成「報告」而不是長篇對話輸出：
 *   1. 表頭是 KPI 欄位帶（分級／ETE／主疏散／通報語言／合規），指揮官掃一眼就有結論
 *   2. 細節分成四個頁籤，避免所有段落堆在同一條垂直捲軸上
 *      處置方案（要做什麼）｜判定依據（為什麼）｜AI 推理（推理過程）｜SOP 原文
 *   3. 敘述文字只留 AI 那一段，其餘資訊一律欄位化或表格化
 *
 * 原本所有區塊平鋪展開，光是一個事件就要滑三、四螢，段落式敘述又和結構化數據混在
 * 一起，看起來像聊天紀錄而不是公文。
 */
export default function AdvisoryCard({
  advisory,
  isSelected,
  onSelect,
  defaultExpanded = false,
}) {
  const [detailOpen, setDetailOpen] = useState(defaultExpanded);
  const [tab, setTab] = useState("plan");
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
          "cursor-pointer rounded-lg border p-4 transition focus-visible:ring-[3px] focus-visible:ring-[var(--ring)]",
          isSelected
            ? "border-[var(--primary)] bg-[var(--primary)]/5"
            : "border-[var(--border)] bg-[var(--card)] hover:bg-[var(--accent)]",
        )}
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-[var(--status-warning)]" />
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
  const trace = advisory.decision_trace;
  const conformance = advisory.sop_conformance;
  const reasoning = advisory.ai_reasoning;

  const eventActions = crossActions.filter((a) => a.scope !== "situational");
  const situationalActions = crossActions.filter((a) => a.scope === "situational");
  const narrativeSource = NARRATIVE_SOURCES[advisory.ai_narrative_source];

  const handleCopy = (e) => {
    e.stopPropagation();
    const lines = [
      `【交控中心建議書】${advisory.event_id}`,
      `分析時間：${advisory.analysis_time || advisory.generated_at}`,
      `事件：${eid.location || eid.affected_segment}（${eid.status} / ${eid.severity}）`,
      `交通分級：${traffic.max_level}`,
      "",
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
      crossActions.forEach((a) =>
        lines.push(`・[${a.sop_reference}] ${a.agency}：${a.request}`),
      );
    }
    const messages = comms.broadcast_messages || [];
    if (messages.length) {
      lines.push("", "公眾通報：");
      messages.forEach((m) => lines.push(`・[${m.language}] ${m.sms_text || m.message}`));
    }
    if (conformance?.summary) lines.push("", `SOP 合規檢核：${conformance.summary}`);
    if (trace?.engine_split?.statement) {
      lines.push(`決策分工：${trace.engine_split.statement}`);
    }
    navigator.clipboard.writeText(lines.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <article
      className={cn(
        "rounded-lg border transition",
        isSelected
          ? "border-[var(--primary)] bg-[var(--primary)]/5 ring-2 ring-[var(--ring)]/30"
          : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--muted-foreground)]/30",
      )}
    >
      {/* ── 報告表頭 ───────────────────────────────────────── */}
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
        className="cursor-pointer rounded-t-lg px-4 pt-3 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-[var(--ring)]"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-sm font-bold">{advisory.event_id}</span>
          <SeverityBadge severity={eid.severity} />
          <LevelBadge level={traffic.max_level} />
          {eid.triggered_sop_articles?.map((s) => (
            <span
              key={s.sop_number}
              title={s.reason}
              className="rounded-sm bg-[var(--status-warning)]/20 px-1.5 py-0.5 text-[10px] font-medium text-[var(--status-warning)]"
            >
              SOP {s.sop_number}
            </span>
          ))}
          {advisory.elapsed_ms != null && (
            <span
              title="本事件端到端處理耗時"
              className="ml-auto flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]"
            >
              <Timer className="h-3 w-3" />
              {(advisory.elapsed_ms / 1000).toFixed(1)} 秒
            </span>
          )}
        </div>

        <div className="mt-1 text-sm text-[var(--muted-foreground)]">
          {eid.location || eid.affected_segment}
          {eid.type && <span className="ml-1.5 text-xs">· {eid.type}</span>}
        </div>

        {/* 人流事件經 affected_road 對應到車流路段時要講清楚，否則分級看起來沒來由 */}
        {eid.traffic_segment_source === "affected_road" && (
          <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
            人流事件經 affected_road 對應車流路段 {eid.traffic_segment}，交通分級與 ETE
            以該路段計算
          </div>
        )}

        {/* KPI 欄位帶：報告的關鍵數字集中在一處 */}
        <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-[var(--border)] pt-2.5 sm:grid-cols-4">
          <Stat
            label="交通分級"
            value={traffic.max_level === "Normal" ? "正常" : `${traffic.max_level} 級`}
            note={`事件路段 ${percent(
              traffic.congestion_details?.find((c) => c.is_incident_segment)
                ?.saturation_score,
            )}`}
            tone={
              traffic.max_level === "A"
                ? "danger"
                : traffic.max_level === "B"
                  ? "warning"
                  : "success"
            }
          />
          <Stat
            label="預計恢復"
            value={ete ? `${ete.ete_minutes} 分` : "—"}
            note={ete ? `基礎 ${ete.base_clearance_minutes} ＋ 壅塞 ${ete.congestion_penalty_minutes}` : "依 SOP 第 7 條"}
            tone="info"
          />
          <Stat
            label="主疏散路徑"
            value={primary?.primary_route_name || "不適用"}
            note={
              primary
                ? `飽和度 ${percent(primary.current_saturation)}｜容量 ${primary.capacity_vph}`
                : "本事件依 SOP 不做替代路徑重規劃"
            }
            tone={primary ? "success" : "muted"}
          />
          <Stat
            label="公眾通報"
            value={`${comms.languages?.length || 0} 種語言`}
            note={
              comms.trigger_multilingual_sop6
                ? "SOP 第 6 條多語已觸發"
                : "未達漫遊門檻，僅中文"
            }
            tone={comms.trigger_multilingual_sop6 ? "accent" : "muted"}
          />
        </dl>

        <div className="mt-2 flex flex-wrap items-center gap-2 pb-3">
          {conformance && (
            <span
              className={cn(
                "rounded-sm px-2 py-0.5 text-[10px] font-medium",
                conformance.compliant
                  ? "bg-[var(--status-success)]/15 text-[var(--status-success)]"
                  : "bg-[var(--status-error)]/15 text-[var(--status-error)]",
              )}
            >
              SOP 合規 {conformance.satisfied_checks}/{conformance.total_checks}
            </span>
          )}
          {trace?.engine_split && (
            <>
              <span
                className={cn(
                  "rounded-sm border px-1.5 py-0.5 text-[10px] font-medium",
                  ENGINE_STYLES.deterministic.cls,
                )}
              >
                程式運算 {trace.engine_split.deterministic} 步
              </span>
              <span
                className={cn(
                  "rounded-sm border px-1.5 py-0.5 text-[10px] font-medium",
                  ENGINE_STYLES.llm.cls,
                )}
              >
                AI 生成 {trace.engine_split.llm} 步
              </span>
            </>
          )}
          {navigation.status === "simulated_published" && (
            <span className="flex items-center gap-1 rounded-sm border border-[var(--status-info)]/30 bg-[var(--status-info)]/10 px-1.5 py-0.5 text-[10px] font-medium text-[var(--status-info)]">
              <Navigation className="h-3 w-3" />
              導航已模擬發布
            </span>
          )}

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopy}
              className="flex items-center gap-1 rounded-md bg-[var(--secondary)] px-2.5 py-1.5 text-xs text-[var(--muted-foreground)] transition hover:bg-[var(--accent)] focus-visible:ring-[3px] focus-visible:ring-[var(--ring)]"
            >
              {copied ? (
                <Check className="h-3 w-3 text-[var(--status-success)]" />
              ) : (
                <Copy className="h-3 w-3" />
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
              className="flex items-center gap-1 rounded-md bg-[var(--secondary)] px-2.5 py-1.5 text-xs text-[var(--muted-foreground)] transition hover:bg-[var(--accent)] focus-visible:ring-[3px] focus-visible:ring-[var(--ring)]"
            >
              {detailOpen ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
              {detailOpen ? "收合" : "展開報告"}
            </button>
          </div>
        </div>
      </div>

      {/* ── 分頁詳情 ───────────────────────────────────────── */}
      {detailOpen && (
        <div className="border-t border-[var(--border)]">
          <nav
            className="flex flex-wrap gap-1 border-b border-[var(--border)] px-3 py-2"
            aria-label="建議書分頁"
          >
            {TABS.map((item) => {
              const Icon = item.icon;
              const active = tab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-current={active ? "true" : undefined}
                  onClick={() => setTab(item.id)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition focus-visible:ring-[3px] focus-visible:ring-[var(--ring)]",
                    active
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]",
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {item.label}
                  {item.id === "clauses" && clauses.length > 0 && (
                    <span className="opacity-70">{clauses.length}</span>
                  )}
                </button>
              );
            })}
          </nav>

          <div className="space-y-3 px-4 py-3">
            {tab === "plan" && (
              <>
                {advisory.ai_narrative && (
                  <section className="rounded-md bg-[var(--primary)]/10 p-3">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      <Bot className="h-3.5 w-3.5 text-[var(--primary)]" />
                      <span className="text-[10px] font-semibold text-[var(--primary)]">
                        AI 決策分析
                      </span>
                      {narrativeSource && (
                        <span
                          className={cn(
                            "text-[10px]",
                            narrativeSource.tone === "warning"
                              ? "text-[var(--status-warning)]"
                              : "text-[var(--muted-foreground)]",
                          )}
                        >
                          （{narrativeSource.label}）
                        </span>
                      )}
                    </div>
                    <div className="whitespace-pre-wrap text-sm leading-relaxed">
                      {advisory.ai_narrative}
                    </div>
                  </section>
                )}

                {fieldActions?.actions?.length > 0 && (
                  <Section title={fieldActions.title} icon={ListChecks}>
                    <ul className="space-y-0.5 text-sm text-[var(--muted-foreground)]">
                      {fieldActions.actions.map((a, i) => (
                        <li key={i}>・{a}</li>
                      ))}
                    </ul>
                  </Section>
                )}

                {primary && (
                  <Section title="替代路徑建議" icon={Route}>
                    <dl className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
                      <Field label="主疏散">
                        <span className="font-medium text-[var(--status-success)]">
                          {primary.primary_route_name}
                        </span>
                        <span className="ml-1.5 text-[var(--muted-foreground)]">
                          飽和度 {percent(primary.current_saturation)}｜容量{" "}
                          {primary.capacity_vph} 車/小時
                        </span>
                      </Field>
                      {primary.secondary_routes?.length > 0 && (
                        <Field label="次要疏散">
                          {primary.secondary_routes
                            .map((r) => `${r.name}（${percent(r.saturation_score)}）`)
                            .join("、")}
                        </Field>
                      )}
                      <Field label="選擇依據">{primary.selection_reason}</Field>
                      {primary.congestion_note && (
                        <Field label="壅塞註記" tone="warning">
                          {primary.congestion_note}
                        </Field>
                      )}
                    </dl>
                    <RouteCandidateTable
                      candidates={analysis?.candidates || primary.excluded_routes}
                      upstream={analysis?.upstream_resolution}
                    />
                  </Section>
                )}

                {route.signal_adjustments?.length > 0 && (
                  <Section title="號誌調整建議" icon={TrafficCone}>
                    <dl className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
                      {route.signal_adjustments.map((s, i) => (
                        <Field key={i} label={s.road_name}>
                          {s.action}
                          {s.window && (
                            <span className="block text-[10px] text-[var(--muted-foreground)]">
                              時段：{s.window}
                            </span>
                          )}
                        </Field>
                      ))}
                    </dl>
                  </Section>
                )}

                {eventActions.length > 0 && (
                  <Section title="跨系統聯動（本事件）" icon={Building2}>
                    <dl className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
                      {eventActions.map((a, i) => (
                        <Field key={i} label={a.agency} tag={a.sop_reference}>
                          {a.request}
                          {a.basis && (
                            <span className="block text-[10px] text-[var(--muted-foreground)]">
                              依據：{a.basis}
                            </span>
                          )}
                        </Field>
                      ))}
                    </dl>
                  </Section>
                )}

                {navigation.status === "simulated_published" && (
                  <Section title="導航資訊更新" icon={Navigation}>
                    <dl className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
                      <Field label="發布狀態">
                        已模擬發布至導航服務（{navigation.published_at}）
                      </Field>
                      <Field label="封閉路段">{navigation.closed_segment_name}</Field>
                      <Field label="改道指引">
                        主疏散 {navigation.primary_route?.name}
                        {navigation.secondary_routes?.length > 0 &&
                          `；次要 ${navigation.secondary_routes
                            .map((item) => item.name)
                            .join("、")}`}
                      </Field>
                    </dl>
                  </Section>
                )}
              </>
            )}

            {tab === "basis" && (
              <>
                {trace && <DecisionTracePanel trace={trace} />}
                {conformance && <SopConformancePanel conformance={conformance} />}

                {traffic.congestion_details?.length > 0 && (
                  <Section title="交通分級判定依據（全路段數據佐證）">
                    <div className="mb-1 text-[10px] text-[var(--muted-foreground)]">
                      事件路段 {traffic.incident_segment} 判定{" "}
                      {traffic.incident_segment_level}；全網最高{" "}
                      {traffic.network_max_level}；城市應變觸發路段最高{" "}
                      {traffic.trigger_max_level}
                    </div>
                    <div className="max-h-44 divide-y divide-[var(--border)] overflow-y-auto rounded-sm border border-[var(--border)]">
                      {traffic.congestion_details.map((c) => (
                        <div
                          key={c.segment_id}
                          className="flex items-center justify-between gap-2 px-2.5 py-1 text-xs"
                        >
                          <span className="truncate text-[var(--muted-foreground)]">
                            {c.road_name}
                            {c.is_trigger_segment && (
                              <span className="ml-1 rounded-sm bg-[var(--accent)] px-1 text-[9px] text-[var(--accent-foreground)]">
                                觸發
                              </span>
                            )}
                            {c.is_incident_segment && (
                              <span className="ml-1 rounded-sm bg-[var(--status-error)]/20 px-1 text-[9px] text-[var(--status-error)]">
                                事件
                              </span>
                            )}
                          </span>
                          <span
                            className={cn(
                              "shrink-0 font-mono font-bold",
                              c.level === "A"
                                ? "text-[var(--status-error)]"
                                : c.level === "B"
                                  ? "text-[var(--status-warning)]"
                                  : "text-[var(--status-success)]",
                            )}
                          >
                            {percent(c.saturation_score)} {c.description}
                          </span>
                        </div>
                      ))}
                    </div>
                  </Section>
                )}

                {ete && (
                  <Section title="預計恢復時間計算">
                    <dl className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
                      <Field label="公式">
                        <code className="font-mono text-[10px]">{ete.formula}</code>
                      </Field>
                      <Field label="基礎清除">
                        嚴重度 {ete.severity} → {ete.base_clearance_minutes} 分鐘
                      </Field>
                      <Field label="壅塞懲罰">
                        {ete.congestion_penalty_minutes} 分鐘
                        {ete.avg_saturation_score != null &&
                          `（受影響路段平均飽和度 ${percent(ete.avg_saturation_score)}）`}
                      </Field>
                      <Field label="受影響路段">
                        {ete.affected_segments_definition}
                        {ete.affected_segments?.length > 0 && (
                          <span className="block text-[10px] text-[var(--muted-foreground)]">
                            納入計算：
                            {ete.affected_segments
                              .map((s) =>
                                s.available
                                  ? `${s.road_name} ${percent(s.saturation_score)}`
                                  : `${s.segment_id}（無車流資料）`,
                              )
                              .join("、")}
                          </span>
                        )}
                      </Field>
                      <Field label="ETE">
                        <span className="font-bold text-[var(--status-info)]">
                          {ete.ete_minutes} 分鐘
                        </span>
                      </Field>
                      {ete.note && (
                        <Field label="註記" tone="warning">
                          {ete.note}
                        </Field>
                      )}
                    </dl>
                  </Section>
                )}

                {comms.roaming_trigger_stations?.length > 0 && (
                  <Section title="SOP 第 6 條多語觸發依據">
                    <p className="mb-1 text-[10px] text-[var(--muted-foreground)]">
                      判定範圍：{comms.roaming_scope || "全資料集所有基地台"}
                    </p>
                    <div className="flex flex-wrap gap-x-3 gap-y-1">
                      {comms.roaming_trigger_stations.map((s) => (
                        <span key={s.bs_id} className="text-xs">
                          {s.location_name}
                          <span className="ml-1 font-mono font-medium text-[var(--chart-5)]">
                            {s.roaming_user_pct_display}
                          </span>
                        </span>
                      ))}
                    </div>
                  </Section>
                )}

                {(situational.length > 0 || situationalActions.length > 0) && (
                  <Section title="同時段全市態勢（非本事件觸發）" icon={Users}>
                    <dl className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
                      {situational.map((s) => (
                        <Field
                          key={s.sop_number}
                          label={`SOP 第 ${s.sop_number} 條`}
                          tag={s.title}
                        >
                          {s.reason}
                        </Field>
                      ))}
                      {situationalActions.map((a, i) => (
                        <Field key={i} label={a.agency} tag={a.sop_reference}>
                          {a.request}
                        </Field>
                      ))}
                    </dl>
                  </Section>
                )}
              </>
            )}

            {tab === "reasoning" && (
              <>
                <Section title="AI 在本事件中的角色">
                  <dl className="divide-y divide-[var(--border)] rounded-sm border border-[var(--border)]">
                    <Field label="分工">
                      {trustStatement(trace) ||
                        "所有門檻判定、路網篩選與公式運算均由程式完成，AI 只負責敘述。"}
                    </Field>
                    <Field label="敘述來源">
                      {narrativeSource?.label || advisory.ai_narrative_source || "—"}
                    </Field>
                    <Field label="推理記錄">
                      {reasoning?.thinking_available
                        ? `已記錄 ${reasoning.thinking_block_count} 段推理、${reasoning.tool_call_count} 次資料核對`
                        : reasoning?.note || "本事件未記錄到 AI 推理軌跡"}
                    </Field>
                  </dl>
                </Section>

                {reasoning ? (
                  <AiReasoningTrace reasoning={reasoning} defaultOpen />
                ) : (
                  <p className="text-xs text-[var(--muted-foreground)]">
                    本事件的建議書敘述由程式依 SOP 判定結果組出（AI 未連線或已進入時限
                    降級），因此沒有 AI 推理軌跡可展示。判定依據請見「判定依據」頁籤。
                  </p>
                )}
              </>
            )}

            {tab === "clauses" && (
              <>
                {clauses.length === 0 ? (
                  <p className="text-xs text-[var(--muted-foreground)]">
                    本事件未引用 SOP 條文。
                  </p>
                ) : (
                  <div className="space-y-2">
                    {clauses.map((c) => (
                      <div key={c.sop_number}>
                        <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold text-[var(--muted-foreground)]">
                          <ScrollText className="h-3 w-3" />
                          SOP 第 {c.sop_number} 條 {c.title}
                        </div>
                        <pre className="whitespace-pre-wrap rounded-md bg-[var(--muted)] p-2.5 font-mono text-xs text-[var(--muted-foreground)]">
                          {c.text}
                        </pre>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      <div className="px-4 pb-4">
        <CMSInline comms={comms} eventId={advisory.event_id} />
      </div>
    </article>
  );
}

/** KPI 欄位：標籤在上、數值在下，附一行依據說明。 */
function Stat({ label, value, note, tone = "muted" }) {
  const tones = {
    danger: "text-[var(--status-error)]",
    warning: "text-[var(--status-warning)]",
    success: "text-[var(--status-success)]",
    info: "text-[var(--status-info)]",
    accent: "text-[var(--chart-5)]",
    muted: "text-[var(--foreground)]",
  };
  return (
    <div className="min-w-0">
      <dt className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </dt>
      <dd>
        <div className={cn("truncate text-sm font-bold", tones[tone])} title={value}>
          {value}
        </div>
        {note && (
          <div className="truncate text-[10px] text-[var(--muted-foreground)]" title={note}>
            {note}
          </div>
        )}
      </dd>
    </div>
  );
}

/** 報告欄位列：左標籤右內容，取代原本的散文段落。 */
function Field({ label, tag, tone, children }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 px-2.5 py-1.5">
      <dt className="w-24 shrink-0 text-xs text-[var(--muted-foreground)]">
        {label}
        {tag && (
          <span className="mt-0.5 block text-[10px] opacity-70">{tag}</span>
        )}
      </dt>
      <dd
        className={cn(
          "min-w-0 flex-1 text-xs leading-relaxed",
          tone === "warning" ? "text-[var(--status-warning)]" : "",
        )}
      >
        {children}
      </dd>
    </div>
  );
}

function Section({ title, icon: Icon, children }) {
  return (
    <section>
      <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
        {Icon && <Icon className="h-3 w-3" />}
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
        "rounded-sm px-2 py-0.5 text-xs font-bold",
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
    <span
      className={cn(
        "rounded-sm px-1.5 py-0.5 text-[10px] font-medium",
        styles[level] || styles.Normal,
      )}
    >
      {labels[level] || "正常"}
    </span>
  );
}
