/**
 * AI 相關顯示字串的單一來源。
 *
 * 工具名稱對照原本寫死在 ChatTab 裡，但建議書的「AI 思考過程」也要顯示同一組
 * 工具名稱，兩邊各寫一份就會漂移。
 */

/** backend/agents/advisor_tools.py 的九個工具，對照成指揮官看得懂的動作。 */
export const TOOL_LABELS = {
  lookup_sop_clause: "查詢 SOP 條文",
  traffic_status: "查詢路網車流",
  crowd_status: "查詢人流與漫遊",
  sop_trigger_status: "查詢 SOP 觸發狀態",
  evacuation_route: "計算疏散路徑",
  recovery_time: "計算 ETE",
  signal_plan: "查詢號誌與警力處置",
  station_detail: "查詢基地台明細",
  network_geometry: "查詢路網幾何",
};

export function toolLabel(name) {
  return TOOL_LABELS[name] || name || "未知工具";
}

/** decision_trace.py 的 engine 欄位 → 畫面徽章樣式。 */
export const ENGINE_STYLES = {
  deterministic: {
    label: "程式運算",
    cls: "bg-[var(--status-success)]/15 text-[var(--status-success)] border-[var(--status-success)]/30",
  },
  llm: {
    label: "AI 生成",
    cls: "bg-[var(--status-info)]/15 text-[var(--status-info)] border-[var(--status-info)]/30",
  },
};

/** decision_trace.py 的合規檢核狀態 → 畫面樣式。 */
export const CONFORMANCE_STYLES = {
  pass: {
    label: "符合",
    cls: "bg-[var(--status-success)]/15 text-[var(--status-success)]",
  },
  degraded: {
    label: "條文退階",
    cls: "bg-[var(--status-warning)]/15 text-[var(--status-warning)]",
  },
  fail: {
    label: "未滿足",
    cls: "bg-[var(--status-error)]/15 text-[var(--status-error)]",
  },
  na: {
    label: "不適用",
    cls: "bg-[var(--muted)] text-[var(--muted-foreground)]",
  },
};
