import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 訂閱後端路網即時狀態。
 *
 * 後端在模擬時間推進時會主動用 WS /ws/dashboard 推播，所以優先走 WebSocket；
 * 連不上或斷線時自動退回 REST 輪詢，輪詢節奏照後端回報的 suggested_poll_seconds。
 * 兩條路徑拿到的都是同一個 _build_status 產物，畫面不會因為傳輸方式而不一致。
 *
 * 另外提供 refresh()：時鐘指令（暫停、跳格）不一定會改變模擬時間，
 * 這種情況後端不會推播，需要呼叫端主動拉一次。
 *
 * 傳入 ts（YYYY-MM-DD HH:MM）表示「回看」該時間：改用 GET /api/status?ts= 取回，
 * 並忽略 WS 的即時推播（推播帶的是直播時間，會蓋掉回看畫面）。?ts= 只影響單次
 * 請求，不會動到後端全域時鐘，也不影響其他連線。
 */
const MIN_POLL_MS = 1000;
const MAX_POLL_MS = 30000;
const IDLE_POLL_MS = 10000;
const WS_RETRY_MS = 6000;

function wsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/dashboard`;
}

export default function useLiveStatus(ts = null) {
  const [status, setStatus] = useState(null);
  // websocket | polling | connecting | offline
  const [transport, setTransport] = useState("connecting");
  const [error, setError] = useState(null);
  // 其他值班席位注入事件時後端會推播建議書，這裡接住讓畫面不必重新整理
  const [pushedReport, setPushedReport] = useState(null);

  const socketRef = useRef(null);
  const pollTimerRef = useRef(null);
  const retryTimerRef = useRef(null);
  const cancelledRef = useRef(false);
  const pollingRef = useRef(false);
  // 目前要看的時間放在 ref，取狀態的函式才能保持穩定，不會每次回看都重連 WS
  const tsRef = useRef(ts);
  tsRef.current = ts;

  const clearPoll = () => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  const fetchStatus = useCallback(async () => {
    const at = tsRef.current;
    try {
      const res = await fetch(at ? `/api/status?ts=${encodeURIComponent(at)}` : "/api/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (cancelledRef.current) return null;
      setStatus(data);
      setError(null);
      return data;
    } catch (err) {
      if (!cancelledRef.current) {
        // 靜默失敗會讓畫面停在舊資料卻毫無提示，這裡明確暴露給使用者
        setError(err.message || "無法取得路網狀態");
        setTransport("offline");
      }
      return null;
    }
  }, []);

  const scheduleNextPoll = useCallback(
    (clock) => {
      clearPoll();
      if (cancelledRef.current || !pollingRef.current) return;
      // 回看指定時間時資料不會自己變，等切到別的時間再抓
      if (tsRef.current) return;
      const hint = clock?.suggested_poll_seconds ?? clock?.next_change_in_seconds;
      const delay =
        hint == null
          ? IDLE_POLL_MS
          : Math.min(Math.max(hint * 1000 + 250, MIN_POLL_MS), MAX_POLL_MS);
      pollTimerRef.current = setTimeout(async () => {
        const data = await fetchStatus();
        scheduleNextPoll(data?.clock);
      }, delay);
    },
    [fetchStatus],
  );

  const startPolling = useCallback(async () => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    setTransport("polling");
    const data = await fetchStatus();
    scheduleNextPoll(data?.clock);
  }, [fetchStatus, scheduleNextPoll]);

  const stopPolling = useCallback(() => {
    pollingRef.current = false;
    clearPoll();
  }, []);

  const connect = useCallback(() => {
    if (cancelledRef.current) return;
    let socket;
    try {
      socket = new WebSocket(wsUrl());
    } catch {
      startPolling();
      return;
    }
    socketRef.current = socket;

    socket.onopen = () => {
      if (cancelledRef.current) return;
      stopPolling();
      setTransport("websocket");
      setError(null);
    };

    socket.onmessage = (event) => {
      if (cancelledRef.current) return;
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "status") {
          // 回看中：推播帶的是直播時間，套用會蓋掉使用者選的時間
          if (tsRef.current) return;
          const { type, ...rest } = payload;
          setStatus(rest);
          setError(null);
        } else if (payload.type === "incident_report" && payload.report) {
          setPushedReport({
            injectionId: payload.injection_id || "",
            eventIds: payload.event_ids || [],
            report: payload.report,
            receivedAt: Date.now(),
          });
        }
      } catch {
        // 單筆訊息解析失敗不該讓整條連線失效
      }
    };

    const fallback = () => {
      socketRef.current = null;
      if (cancelledRef.current) return;
      startPolling();
      // 定期嘗試回到 WebSocket，恢復後就不必再輪詢
      if (!retryTimerRef.current) {
        retryTimerRef.current = setTimeout(() => {
          retryTimerRef.current = null;
          connect();
        }, WS_RETRY_MS);
      }
    };

    socket.onerror = fallback;
    socket.onclose = fallback;
  }, [startPolling, stopPolling]);

  // 初次載入與每次切換回看時間都主動取一次；不等 WS 握手，畫面能立刻有內容。
  // 從回看切回 LIVE 時，若目前走的是輪詢，也要把輪詢鏈接回去。
  useEffect(() => {
    let stale = false;
    fetchStatus().then((data) => {
      if (!stale && !tsRef.current) scheduleNextPoll(data?.clock);
    });
    return () => {
      stale = true;
    };
  }, [ts, fetchStatus, scheduleNextPoll]);

  useEffect(() => {
    cancelledRef.current = false;
    connect();
    return () => {
      cancelledRef.current = true;
      stopPolling();
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket) {
        socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
        socket.close();
      }
    };
  }, [connect, stopPolling]);

  return { status, transport, error, pushedReport, refresh: fetchStatus };
}
