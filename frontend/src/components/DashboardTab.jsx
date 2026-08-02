import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ThreatGrid from "./ThreatGrid";
import CityMap3D from "./CityMap3D";
import SopTriggerPanel from "./SopTriggerPanel";
import StreamTimeline from "./StreamTimeline";
import AlertCenter from "./AlertCenter";

/**
 * 即時儀表板
 *
 * 一個畫面看完路網現況：地圖 + 串流時間軸、即時路網監測、SOP 自動偵測
 * （資料型條款 data_triggers，對應 SOP 第 3、4、6 條）。
 *
 * SOP 第 1 條的自動應變（auto_advisories）與僅監控清單（monitored_alerts）
 * 不在這裡展開，改由「路網即時監控」分頁與左上角的預警中心呈現，
 * 儀表板才不會被長條列表撐出捲軸。
 *
 * 自動預警由地圖左上角的預警中心（AlertCenter）呈現：新的異常以 toast 提示
 * （不遮蔽畫面、不搶焦點、靜置後自動收起），收起後仍留下「預警紀錄」入口，
 * 可回看過往每一筆預警的當時快照。
 *
 * 摘要向 /api/alert-summary 取得（LLM 生成），門檻判定仍在後端程式，
 * 對應命題「摘要由 LLM 生成，門檻判定由程式運算」。
 */
// 紀錄上限：Demo 的共同時間軸只有十幾格，留 20 筆足夠且不會無限成長
const MAX_ALERT_HISTORY = 20;

/**
 * 挑一個最該讓鏡頭飛過去的路段：A 級優先於 B 級，同級以「城市應變觸發路段」
 * 為先，再比飽和度。觸發路段的認定沿用後端的 is_trigger_segment，
 * 前端不自行判斷哪幾段屬於觸發路段。
 */
function pickFocusSegment(abnormal) {
  if (!abnormal.length) return null;
  const weight = (s) =>
    (s.level === "A" ? 200 : 100) +
    (s.is_trigger_segment ? 50 : 0) +
    (s.saturation_score || 0);
  return [...abnormal].sort((a, b) => weight(b) - weight(a))[0];
}

export default function DashboardTab({ network, stream, onInspectSegment }) {
  const {
    segments,
    stations,
    timestamp,
    dataAsOf,
    monitoredAlerts,
    dataTriggers,
    thresholds,
  } = network;

  // 預警紀錄（最新在最前面）。toast 自動收起後過往預警仍可回看，
  // 每筆保存偵測當時的快照，回看時不會被現在的路網狀態覆寫。
  const [alertHistory, setAlertHistory] = useState([]);
  const [activeAlertId, setActiveAlertId] = useState(null);
  const seenSignatureRef = useRef(null);
  // 地圖相機的聚焦目標：偵測到新的預警時換一次，CityMap3D 依此飛抵並環繞
  const [focusTarget, setFocusTarget] = useState(null);

  // 異常特徵：異常路段組合或觸發條款有變化就視為一筆新的預警。
  // 原本用一個 boolean 記「已彈過」，整場 Demo 只會跳一次，
  // 之後時間推進出現新的癱瘓路段完全沒有提示。
  const signature = useMemo(() => {
    const abnormal = segments
      .filter((s) => s.level === "A" || s.level === "B")
      .map((s) => `${s.segment_id}:${s.level}`)
      .sort()
      .join(",");
    const sops = [...(dataTriggers?.triggered_numbers || [])].sort().join(",");
    return abnormal || sops ? `${abnormal}|${sops}` : "";
  }, [segments, dataTriggers]);

  // 摘要是非同步取得的，回填時用 id 對應到那一筆紀錄，
  // 期間若又偵測到新的預警也不會把摘要寫到錯誤的紀錄上。
  const loadSummary = useCallback(async (id, ts) => {
    try {
      const query = ts ? `?ts=${encodeURIComponent(ts)}` : "";
      const res = await fetch(`/api/alert-summary${query}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAlertHistory((prev) =>
        prev.map((e) => (e.id === id ? { ...e, summary: data, summaryState: "ready" } : e)),
      );
    } catch {
      setAlertHistory((prev) =>
        prev.map((e) => (e.id === id ? { ...e, summaryState: "error" } : e)),
      );
    }
  }, []);

  useEffect(() => {
    if (!signature) {
      // 路網恢復正常就把記憶清掉：同一組異常之後再度發生時算一起新事件，
      // 會另外留下一筆紀錄，而不是被誤判成同一次而靜默。
      seenSignatureRef.current = null;
      return;
    }
    // 同一組異常只留一筆紀錄、只提示一次；模擬時間推進不會重複灌爆紀錄。
    if (seenSignatureRef.current === signature) return;
    seenSignatureRef.current = signature;

    const abnormal = segments.filter((s) => s.level === "A" || s.level === "B");
    const entry = {
      id: `${timestamp || "-"}#${signature}`,
      signature,
      detectedAt: timestamp || "",
      levelCounts: {
        A: abnormal.filter((s) => s.level === "A").length,
        B: abnormal.filter((s) => s.level === "B").length,
      },
      // 快照只留呈現需要的欄位，避免整份 segments 被長期持有
      triggerSegments: abnormal
        .filter((s) => s.is_trigger_segment)
        .map((s) => ({
          segment_id: s.segment_id,
          road_name: s.road_name,
          level: s.level,
          level_description: s.level_description,
          saturation_score: s.saturation_score,
          avg_speed: s.avg_speed,
        })),
      monitoredAlerts: monitoredAlerts.map((m) => ({
        road_name: m.road_name,
        level_description: m.level_description,
      })),
      summary: null,
      summaryState: "loading",
    };

    setAlertHistory((prev) => [entry, ...prev].slice(0, MAX_ALERT_HISTORY));
    setActiveAlertId(entry.id);
    loadSummary(entry.id, timestamp);

    // 自動導播：鏡頭飛到最嚴重的路段並環繞，直到指揮官操作地圖接手。
    // key 用預警 id，同一筆預警不會因為輪詢而把鏡頭反覆拉回去。
    const focus = pickFocusSegment(abnormal);
    if (focus) {
      setFocusTarget({
        key: entry.id,
        segmentId: focus.segment_id,
        label: focus.road_name,
      });
    }
  }, [signature, timestamp, segments, monitoredAlerts, loadSummary]);

  return (
    // 填滿 App 給的剩餘高度：地圖與監測小卡吃掉可用空間，整頁不需要往下捲
    // relative：預警中心以此為定位基準疊在左上角
    <div className="relative h-full min-h-0 flex flex-col">
      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-4 gap-4">
        {/* 左欄：地圖與時間軸緊貼成一體，兩者之間不留間距，
            共用外框圓角（地圖只圓上緣、時間軸只圓下緣） */}
        <div className="xl:col-span-3 flex flex-col min-h-0">
          <CityMap3D
            segments={segments}
            stations={stations}
            thresholds={thresholds}
            focusTarget={focusTarget}
            onSegmentClick={onInspectSegment}
            className="flex-1 min-h-0 rounded-b-none"
          />
          <StreamTimeline stream={stream} className="shrink-0 rounded-t-none border-t-0" />
        </div>

        {/* 右欄：即時路網監測，下方接資料型 SOP（第 3、4、6 條）的自動偵測 */}
        <div className="xl:col-span-1 flex flex-col gap-4 min-h-0">
          <ThreatGrid
            segments={segments}
            timestamp={timestamp}
            onSelect={onInspectSegment}
            className="flex-1 min-h-0"
          />
          <SopTriggerPanel
            dataTriggers={dataTriggers}
            dataAsOf={dataAsOf}
            className="shrink-0 max-h-[45%]"
          />
        </div>
      </div>

      <AlertCenter
        history={alertHistory}
        activeId={activeAlertId}
        onSelect={setActiveAlertId}
      />
    </div>
  );
}
