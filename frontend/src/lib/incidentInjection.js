/**
 * 事件注入 API（管理員介面專用）
 *
 * 後端的驗證錯誤一律是 { error: { code, message, trace_id, details[] } }，
 * 這裡統一轉成 IncidentApiError，讓元件只處理一種錯誤形狀。
 */

/** 後端契約層回報的注入錯誤，帶穩定代碼與逐欄位明細。 */
export class IncidentApiError extends Error {
  constructor({ code, message, traceId = "", details = [] }) {
    super(message);
    this.name = "IncidentApiError";
    this.code = code;
    this.traceId = traceId;
    this.details = details;
  }
}

async function request(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch {
    throw new IncidentApiError({ code: "NETWORK_ERROR", message: "無法連線到事件注入服務" });
  }

  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }

  if (!res.ok) {
    const error = body?.error;
    throw new IncidentApiError({
      code: error?.code || `HTTP_${res.status}`,
      message: error?.message || "事件注入服務回應異常",
      traceId: error?.trace_id || "",
      details: error?.details || [],
    });
  }
  return body;
}

const jsonBody = (payload) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

/** 可注入的路段、人流站點、合法列舉值與 live_incidents.json 範本。 */
export function fetchInjectionCatalog() {
  return request("/api/incidents/catalog");
}

/** 驗證事件內容並取得預覽（不執行 Agent）。 */
export async function previewIncidents({ payload, simTime = "" }) {
  const body = await request("/api/incidents/preview", jsonBody({ payload, sim_time: simTime }));
  return body.preview;
}

/** 上傳 live_incidents.json 取得預覽；副檔名與大小規則由後端把關。 */
export async function previewUploadedIncidents({ file, simTime = "" }) {
  const form = new FormData();
  form.append("file", file);
  const query = simTime ? `?ts=${encodeURIComponent(simTime)}` : "";
  const body = await request(`/api/incidents/preview/upload${query}`, {
    method: "POST",
    body: form,
  });
  return body.preview;
}

/**
 * 確認後注入。preview_hash 與 confirmations 必須來自剛剛的預覽，
 * 後端會重新驗證一次，內容被改過就會被拒。
 */
export function injectIncidents({
  payload,
  previewHash,
  confirmations,
  simTime = "",
  sessionId = "",
  adminToken = "",
}) {
  const headers = { "Content-Type": "application/json" };
  if (adminToken) headers["X-Admin-Token"] = adminToken;
  return request("/api/incidents/inject", {
    method: "POST",
    headers,
    body: JSON.stringify({
      payload,
      preview_hash: previewHash,
      confirmations,
      sim_time: simTime,
      session_id: sessionId,
    }),
  });
}

/** 近期注入紀錄（新到舊）。include_report 為 true 時一併帶回建議書。 */
export function fetchRecentInjections({ limit = 5, includeReport = false } = {}) {
  const params = new URLSearchParams({
    limit: String(limit),
    include_report: String(includeReport),
  });
  return request(`/api/incidents/injections?${params}`);
}

/**
 * 把目錄範本轉回可注入的事件。
 * 範本額外帶了 _category / _category_label 供 UI 標示，
 * 但契約層禁止未知欄位，送出前必須清掉。
 */
export function templateToEvent(template) {
  return Object.fromEntries(
    Object.entries(template).filter(([key]) => !key.startsWith("_")),
  );
}

/** 附加事件時避免 event_id 撞號，否則會直接被判為重複事件。 */
export function withUniqueEventId(event, existingIds) {
  if (!existingIds.includes(event.event_id)) return event;
  let suffix = 2;
  while (existingIds.includes(`${event.event_id}_${suffix}`)) suffix += 1;
  return { ...event, event_id: `${event.event_id}_${suffix}` };
}

export const CONFIRMATION_LABELS = {
  payload: "已核對事件內容與影響路段",
  future_simulation: "已知悉事件時間晚於當下模擬時間，將提前套用該時段資料",
};
