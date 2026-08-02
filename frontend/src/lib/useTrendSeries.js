import { useEffect, useState } from "react";

/**
 * 飽和度時序資料（GET /api/trend）。
 *
 * 後端只回傳「截至查詢時間」的資料點，尾端補一個當下的插值點，因此時間一推進就要重抓。
 * 一定要帶 ts：回看模式下畫面顯示的是過去某個時間的路網，若不帶 ts 就會拿到
 * 後端全域時鐘的當下趨勢，曲線與頁首數值對不上。
 *
 * 監控頁只呼叫一次，螢幕上的圖與匯出報告的圖共用同一份資料，兩者不會出現落差。
 *
 * @param {string|null} simTime 目前檢視的模擬時間（YYYY-MM-DD HH:MM）
 */
export default function useTrendSeries(simTime) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const query = simTime ? `?ts=${encodeURIComponent(simTime)}` : "";
    fetch(`/api/trend${query}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload) => {
        if (cancelled) return;
        setData(payload.data || []);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setData([]);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [simTime]);

  return { data, loading };
}
