import { useEffect, useState } from "react";

/**
 * 單一路段的預警摘要（GET /api/alert-summary?segment_id=&ts=）。
 *
 * 後端把分級、趨勢與應變內容算完後才交給語言模型寫敘述，門檻判定不經 AI；
 * 回傳內容除了摘要文字，還包含程式算出的趨勢統計與引用的 SOP 條文原文，
 * 監控頁與匯出的報告共用同一份，畫面與報告不會出現兩套說法。
 *
 * 只在路段達 A/B 級時查詢：未達門檻時沒有預警可言，也不需要花一次模型呼叫。
 *
 * @param {string|null} segmentId 路段代號
 * @param {string|null} simTime   目前檢視的模擬時間（YYYY-MM-DD HH:MM）
 * @param {boolean} enabled       是否查詢（建議傳入「是否達 A/B 級」）
 */
export default function useSegmentAlertSummary(segmentId, simTime, enabled = true) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!segmentId || !enabled) {
      setSummary(null);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({ segment_id: segmentId });
    if (simTime) params.set("ts", simTime);

    fetch(`/api/alert-summary?${params.toString()}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload) => {
        if (cancelled) return;
        setSummary(payload);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setSummary(null);
        setError(err.message || "摘要取得失敗");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [segmentId, simTime, enabled]);

  return { summary, loading, error };
}
