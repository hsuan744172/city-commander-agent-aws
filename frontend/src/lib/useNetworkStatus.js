import { useMemo } from "react";

import useLiveStatus from "./useLiveStatus";

/**
 * 路網即時狀態（GET /api/status，優先走 WS /ws/dashboard 推播）。
 *
 * 儀表板與事件處置頁共用同一份資料格式，避免各自實作訂閱邏輯。
 * 傳輸細節在 useLiveStatus，這裡只把後端欄位攤平成元件慣用的形狀。
 *
 * @returns {{
 *   segments: Array, stations: Array, timestamp: string, dataAsOf: string,
 *   autoAdvisories: Array, monitoredAlerts: Array, dataTriggers: Object,
 *   thresholds: Object, clock: Object, hasAlert: boolean, dataMode: string,
 *   transport: string, error: string|null, pushedReport: Object|null,
 *   refresh: Function,
 * }}
 */
export default function useNetworkStatus() {
  const { status, transport, error, pushedReport, refresh } = useLiveStatus();

  return useMemo(
    () => ({
      segments: status?.segments || [],
      stations: status?.stations || [],
      timestamp: status?.timestamp || "",
      dataAsOf: status?.data_as_of || "",
      // SOP 第 1 條城市應變觸發路段的自動應變
      autoAdvisories: status?.auto_advisories || [],
      // 非觸發路段達 A/B 級，只做燈號顯示
      monitoredAlerts: status?.monitored_alerts || [],
      // SOP 第 3、4、6 條的主動偵測結果
      dataTriggers: status?.data_triggers || { triggered_numbers: [], checks: [] },
      // 門檻由後端提供，前端不再自己寫死
      thresholds: status?.thresholds || null,
      clock: status?.clock || null,
      hasAlert: Boolean(status?.has_alert),
      dataMode: status?.data_mode || "",
      transport,
      error,
      pushedReport,
      refresh,
    }),
    [status, transport, error, pushedReport, refresh],
  );
}
