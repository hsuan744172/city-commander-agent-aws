import { useEffect, useState } from "react";

// 輪詢節奏：後端模擬時鐘會回報下一次時間變動的秒數，前端照它排程。
const MIN_POLL_MS = 1000;
const MAX_POLL_MS = 30000;
const IDLE_POLL_MS = 10000;

/**
 * 路網即時狀態輪詢（GET /api/status）
 * 儀表板與事件處置頁共用同一份資料格式，避免各自實作輪詢邏輯。
 *
 * @returns {{ segments: Array, stations: Array, timestamp: string, autoAdvisories: Array }}
 */
export default function useNetworkStatus() {
  const [status, setStatus] = useState({
    segments: [],
    stations: [],
    timestamp: "",
    autoAdvisories: [],
  });

  useEffect(() => {
    let timer;
    let cancelled = false;

    const scheduleNext = (clock) => {
      const hint = clock?.suggested_poll_seconds ?? clock?.next_change_in_seconds;
      const delay =
        hint == null
          ? IDLE_POLL_MS
          : Math.min(Math.max(hint * 1000 + 250, MIN_POLL_MS), MAX_POLL_MS);
      timer = setTimeout(load, delay);
    };

    const load = async () => {
      let clock = null;
      try {
        const res = await fetch("/api/status");
        const data = await res.json();
        if (cancelled) return;

        clock = data.clock;
        setStatus({
          segments: data.segments || [],
          stations: data.stations || [],
          timestamp: data.timestamp || "",
          autoAdvisories: data.auto_advisories || [],
        });
      } catch {}
      if (!cancelled) scheduleNext(clock);
    };

    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return status;
}
