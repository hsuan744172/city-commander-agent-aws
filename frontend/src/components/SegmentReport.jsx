import { createPortal } from "react-dom";
import TrendChart from "./TrendChart";

/**
 * 路段即時監控報告（列印 / 匯出 PDF）
 *
 * 以 portal 掛在 document.body 底下的 #print-root，螢幕上永遠隱藏（樣式見 index.css），
 * 只有列印時才顯示，因此不影響監控頁版面，也不需要另開視窗或引入排版套件。
 *
 * 內容定位對應命題模組 1（動態時序監測儀表板）：主動偵測、預警與預防性處置。
 * 事件注入才會產出的「交控中心建議書」與多語民眾簡訊屬模組 2，不在本報告範圍，
 * 報告頁尾會明確標示這條界線，避免與建議書混為一談。
 *
 * 報告只呈現已由後端算好的數值（sop_rules / traffic_math / _auto_advisory_for），
 * 唯一由 LLM 生成的是「AI 值班指揮官研判」那一段，且會標注生成來源。
 */

const ROLE_LABEL = {
  primary: { text: "主疏散", cls: "report-badge-primary" },
  secondary: { text: "次要", cls: "report-badge-secondary" },
  excluded: { text: "排除", cls: "report-badge-excluded" },
};

const DATA_SOURCES = [
  "city_traffic_flow.csv（路段車流與飽和度）",
  "road_network_geometry.json（路網拓樸、承載容量、替代路線）",
  "emergency_traffic_sop.txt（交通應變標準程序）",
];

function pct(value) {
  if (value == null) return "無資料";
  return `${Math.round(Number(value) * 100)}%`;
}

function badgeClass(level) {
  if (level === "A") return "report-badge report-badge-a";
  if (level === "B") return "report-badge report-badge-b";
  return "report-badge report-badge-normal";
}

/** 報告編號：由資料時間與路段代號組成，同一時間點的同一路段編號固定可追溯。 */
function reportNumber(simTime, segmentId) {
  const digits = String(simTime || "").replace(/\D/g, "");
  const stamp = digits.slice(0, 12) || "000000000000";
  const seq = String(segmentId || "").replace(/[^0-9]/g, "").slice(-3) || "000";
  return `TCC-M1-${stamp.slice(0, 8)}-${stamp.slice(8, 12)}-${seq}`;
}

export default function SegmentReport({
  segment,
  segments = [],
  advisory = null,
  monitoredAlert = null,
  thresholds = null,
  simTime = "",
  trendData = [],
  aiSummary = null,
  camera = null,
  snapshotDataUrl = null,
  generatedAt = "",
  triggerSegmentNames = [],
}) {
  if (!segment) return null;

  const levelA = thresholds?.level_a ?? 0.95;
  const levelB = thresholds?.level_b ?? 0.85;
  const trend = aiSummary?.trend?.available ? aiSummary.trend : null;
  const ete = advisory?.ete_breakdown || null;
  const signalAdjustments = advisory?.signal_plan?.adjustments || [];
  const candidates = advisory?.route_candidates || [];
  const clauses = aiSummary?.sop_clauses || [];
  const networkTriggers = aiSummary?.network_context?.triggered_sop_numbers || [];

  const roadNameOf = (segmentId) =>
    segments.find((s) => s.segment_id === segmentId)?.road_name || segmentId;

  const levelBasis =
    segment.level === "A"
      ? `飽和度 ${pct(segment.saturation_score)} ≥ A 級門檻 ${pct(levelA)}`
      : segment.level === "B"
        ? `飽和度 ${pct(segment.saturation_score)} 介於 B 級門檻 ${pct(levelB)} 與 A 級門檻 ${pct(levelA)} 之間`
        : `飽和度 ${pct(segment.saturation_score)} 未達 B 級門檻 ${pct(levelB)}`;

  return createPortal(
    <div id="print-root">
      <article className="report">
        <header className="report-doc-header">
          <div className="report-agency">臺 北 市 交 通 管 制 中 心</div>
          <h1 className="report-doc-title">路段即時監控預警報告</h1>
          <div className="report-doc-subtitle">
            城市應變指揮官 AI Agent 自動產製　·　動態時序監測（預警與預防階段）
          </div>
        </header>

        <table className="report-meta">
          <tbody>
            <tr>
              <th scope="row">報告編號</th>
              <td>{reportNumber(simTime, segment.segment_id)}</td>
              <th scope="row">判定級別</th>
              <td>
                <span className={badgeClass(segment.level)}>
                  {segment.level_description || "正常"}
                </span>
              </td>
            </tr>
            <tr>
              <th scope="row">監控路段</th>
              <td>{segment.road_name}</td>
              <th scope="row">路段代號</th>
              <td>{segment.segment_id}</td>
            </tr>
            <tr>
              <th scope="row">資料時間</th>
              <td>{simTime || "—"}</td>
              <th scope="row">應變觸發路段</th>
              <td>{segment.is_trigger_segment ? "是" : "否"}</td>
            </tr>
            <tr>
              <th scope="row">產製時間</th>
              <td colSpan={3}>
                {generatedAt || "—"}
                <span className="report-note" style={{ display: "inline", marginLeft: 8 }}>
                  （產製時間為實際時間；資料時間為模擬時間軸）
                </span>
              </td>
            </tr>
          </tbody>
        </table>

        {/* ---------------------------------------------------------------- */}
        <section className="report-section">
          <h2>一、預警判定（程式運算）</h2>
          <table className="report-table">
            <caption>
              分級門檻與判定結果均由程式依交通應變標準程序第 1 條運算，AI 不參與判定。
            </caption>
            <thead>
              <tr>
                <th scope="col">觀測項目</th>
                <th scope="col">數值</th>
                <th scope="col">判定依據</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">車流飽和度</th>
                <td className="num">{pct(segment.saturation_score)}</td>
                <td>{levelBasis}</td>
              </tr>
              <tr>
                <th scope="row">平均時速</th>
                <td className="num">{segment.avg_speed} 公里/小時</td>
                <td>路段車流量測值</td>
              </tr>
              <tr>
                <th scope="row">車流量</th>
                <td className="num">{segment.vehicle_count} 輛</td>
                <td>路段車流量測值</td>
              </tr>
              <tr>
                <th scope="row">車道狀態</th>
                <td>{segment.lane_status_label || segment.lane_status}</td>
                <td>路段車流量測值</td>
              </tr>
              <tr>
                <th scope="row">交通擁塞級別</th>
                <td>
                  <span className={badgeClass(segment.level)}>
                    {segment.level_description || "正常"}
                  </span>
                </td>
                <td>
                  第 1 條分級：B 級 {pct(levelB)} 以上、A 級 {pct(levelA)} 以上
                </td>
              </tr>
              <tr>
                <th scope="row">城市應變觸發路段</th>
                <td>{segment.is_trigger_segment ? "是" : "否"}</td>
                <td>
                  第 1 條列舉之觸發路段
                  {triggerSegmentNames.length > 0 && `：${triggerSegmentNames.join("、")}`}
                </td>
              </tr>
            </tbody>
          </table>

          {networkTriggers.length > 0 && (
            <p className="report-note">
              同時段全路網另觸發標準程序第 {networkTriggers.join("、")} 條（人流與信令條款），
              不屬本路段車流判定範圍，請併同全網態勢研判。
            </p>
          )}
        </section>

        {/* ---------------------------------------------------------------- */}
        <section className="report-section">
          <h2>二、飽和度趨勢</h2>
          <figure className="report-figure">
            <TrendChart
              variant="print"
              selectedSegment={segment}
              data={trendData}
              thresholds={thresholds}
            />
            <figcaption>
              圖一　{segment.road_name}飽和度時序變化
              {trend && `（${trend.window_start} 至 ${trend.window_end}）`}
              ；橫向虛線為第 1 條 A 級與 B 級分級門檻。
            </figcaption>
          </figure>

          {trend ? (
            <p style={{ marginTop: 6 }}>
              近 {trend.window_minutes} 分鐘內，飽和度由 {pct(trend.first_saturation_score)}
              {trend.direction_label}至 {pct(trend.current_saturation_score)}，
              變化 {trend.delta_percentage_points} 個百分點；期間峰值{" "}
              {pct(trend.peak_saturation_score)} 出現於 {trend.peak_time}。
              {trend.reached_level_a_at
                ? `本路段於 ${trend.reached_level_a_at} 首次達 A 級門檻。`
                : trend.reached_level_b_at
                  ? `本路段於 ${trend.reached_level_b_at} 首次達 B 級門檻。`
                  : ""}
            </p>
          ) : (
            <p className="report-note">趨勢區間資料不足，僅呈現當下量測值。</p>
          )}
        </section>

        {/* ---------------------------------------------------------------- */}
        {aiSummary?.summary && (
          <section className="report-section">
            <h2>三、AI 值班指揮官研判</h2>
            <div className="report-ai">
              {String(aiSummary.summary)
                .split(/\n+/)
                .filter(Boolean)
                .map((paragraph, index) => (
                  <p key={index}>{paragraph}</p>
                ))}
            </div>
            <p className="report-note">
              本段為語言模型依前述程式判定結果撰寫之研判敘述
              {aiSummary.source === "ai_generated"
                ? "（Amazon Bedrock 生成）"
                : "（模型未連線，以程式判定結果直述）"}
              。分級門檻、趨勢變化與所有數值計算均由程式完成，語言模型不參與判定。
            </p>
          </section>
        )}

        {/* ---------------------------------------------------------------- */}
        <section className="report-section">
          <h2>四、應變處置建議</h2>

          {advisory ? (
            <>
              <p>
                依據：{advisory.sop_reference}
                。本路段屬城市應變觸發路段，處置如下。
              </p>

              {signalAdjustments.length > 0 && (
                <>
                  <h3>4.1　號誌配時調整</h3>
                  <table className="report-table">
                    <caption>依第 1 條對替代道路實施長綠燈時制。</caption>
                    <thead>
                      <tr>
                        <th scope="col">調整路段</th>
                        <th scope="col">調整內容</th>
                        <th scope="col">實施時段</th>
                      </tr>
                    </thead>
                    <tbody>
                      {signalAdjustments.map((item) => (
                        <tr key={item.road_name}>
                          <td>{item.road_name}</td>
                          <td>{item.action}</td>
                          <td>{advisory.window || "依現場滾動調整"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}

              {advisory.police_dispatch?.instruction && (
                <>
                  <h3>4.2　警力調度</h3>
                  <p>
                    {advisory.police_dispatch.instruction}
                    {advisory.police_dispatch.staffing_note &&
                      `　${advisory.police_dispatch.staffing_note}`}
                  </p>
                </>
              )}

              {advisory.primary_route && (
                <>
                  <h3>4.3　替代路徑引導</h3>
                  <p>
                    主疏散路段：{advisory.primary_route}（飽和度{" "}
                    {pct(advisory.primary_saturation)}）。
                    {advisory.selection_reason && `　${advisory.selection_reason}`}
                  </p>
                  {advisory.secondary_routes?.length > 0 && (
                    <p>
                      次要疏散路段：
                      {advisory.secondary_routes
                        .map((r) => `${r.name}（${pct(r.saturation_score)}）`)
                        .join("、")}
                      。
                    </p>
                  )}
                  {advisory.upstream_resolution?.detail && (
                    <p className="report-note">
                      上下游判定：{advisory.upstream_resolution.detail}
                      {advisory.upstream_resolution.method &&
                        `（判定方法：${advisory.upstream_resolution.method}）`}
                    </p>
                  )}

                  {candidates.length > 0 && (
                    <table className="report-table" style={{ marginTop: 6 }}>
                      <caption>
                        表一　候選替代道路評估（{candidates.length} 條
                        {candidates.some((c) => c.role === "excluded") && "，含排除理由"}）
                      </caption>
                      <thead>
                        <tr>
                          <th scope="col">候選路段</th>
                          <th scope="col">承載容量</th>
                          <th scope="col">飽和度</th>
                          <th scope="col">相交</th>
                          <th scope="col">上游</th>
                          <th scope="col">判定理由</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...candidates]
                          .sort((a, b) => {
                            const order = { primary: 0, secondary: 1, excluded: 2 };
                            return (order[a.role] ?? 3) - (order[b.role] ?? 3);
                          })
                          .map((candidate) => {
                            const role = ROLE_LABEL[candidate.role] || ROLE_LABEL.excluded;
                            return (
                              <tr key={candidate.segment_id}>
                                <td>
                                  <span className={`report-badge-role ${role.cls}`}>
                                    {role.text}
                                  </span>
                                  {candidate.name}
                                </td>
                                <td className="num">{candidate.capacity_vph} 輛/小時</td>
                                <td className="num">{pct(candidate.saturation_score)}</td>
                                <td>{candidate.is_intersecting ? "是" : "否"}</td>
                                <td>{candidate.is_upstream ? "是" : "否"}</td>
                                <td>{candidate.reason}</td>
                              </tr>
                            );
                          })}
                      </tbody>
                    </table>
                  )}
                </>
              )}

              {advisory.ete_minutes != null && ete && (
                <>
                  <h3>4.4　預計交通恢復時間</h3>
                  <p>
                    預計恢復時間 {advisory.ete_minutes} 分鐘 ＝ 基礎清除{" "}
                    {ete.base_clearance_minutes} 分鐘 ＋ 壅塞懲罰{" "}
                    {ete.congestion_penalty_minutes} 分鐘。
                  </p>
                  <table className="report-table">
                    <caption>依標準程序第 7 條公式計算。</caption>
                    <tbody>
                      <tr>
                        <th scope="row">計算公式</th>
                        <td>{ete.formula}</td>
                      </tr>
                      <tr>
                        <th scope="row">嚴重度取值</th>
                        <td>
                          {ete.severity}　{ete.severity_basis}
                        </td>
                      </tr>
                      <tr>
                        <th scope="row">受影響路段</th>
                        <td>
                          {(ete.affected_segment_ids || []).map(roadNameOf).join("、") || "—"}
                        </td>
                      </tr>
                      <tr>
                        <th scope="row">受影響路段平均飽和度</th>
                        <td className="num">{pct(ete.avg_saturation_score)}</td>
                      </tr>
                    </tbody>
                  </table>
                </>
              )}
            </>
          ) : (
            <>
              <p>
                本路段
                {monitoredAlert?.level_description || segment.level_description}
                ，但不在標準程序第 1 條列舉的城市應變觸發路段
                {triggerSegmentNames.length > 0 && `（${triggerSegmentNames.join("、")}）`}
                之內。依條文規定，僅納入紅黃燈顯示與持續監控，不啟動長綠燈時制，
                亦不啟動第 2 條替代路徑引導。
              </p>
              <h3>4.1　建議作為</h3>
              <p>
                持續監控本路段飽和度變化並實施預防性疏導；
                若飽和度升抵 {pct(levelA)} 即達 A 級門檻，應重新研判處置層級。
                若本路段因後續突發事件被通報封閉或阻斷，改依標準程序第 2 條
                於事件注入流程產出交控中心建議書。
              </p>
            </>
          )}
        </section>

        {/* ---------------------------------------------------------------- */}
        <section className="report-section">
          <h2>五、路段即時影像</h2>
          {snapshotDataUrl ? (
            <figure className="report-figure">
              <img src={snapshotDataUrl} alt={`${segment.road_name}路段即時影像`} />
              <figcaption>
                圖二　{camera?.name || "路段鄰近攝影機"}
                {camera?.distance_m != null && `（距路段約 ${camera.distance_m} 公尺）`}
                {camera?.mode === "hls"
                  ? "；影像來源：政府公開路口監視器直播"
                  : "；影像來源：政府公開路口監視器快照"}
              </figcaption>
            </figure>
          ) : (
            <p className="report-note">
              本路段周邊無可用之公開即時影像，或影像於報告產製時無法取得。
            </p>
          )}
          <p className="report-note">
            影像為報告產製時該路段的實際現地畫面，僅供輔助確認現場環境；
            與模擬時間軸的車流數據並非同一時間來源，不參與分級判定、
            替代路徑計算或恢復時間估算。
          </p>
        </section>

        {/* ---------------------------------------------------------------- */}
        {clauses.length > 0 && (
          <section className="report-section">
            <h2>六、判定依據條文原文</h2>
            {clauses.map((clause) => (
              <pre key={clause.sop_number} className="report-clause">
                {clause.text}
              </pre>
            ))}
          </section>
        )}

        <footer className="report-footer">
          <div>
            本報告由城市應變指揮官 AI Agent 於 {generatedAt} 自動產製，
            內容依據資料時間 {simTime} 之路網量測值。
          </div>
          <div>資料來源：{DATA_SOURCES.join("、")}</div>
          <div>
            本報告屬監測預警階段之路段研判紀錄；突發事件之交控中心建議書與多語民眾
            通報訊息另於事件注入流程產出，不含於本報告。
          </div>
        </footer>
      </article>
    </div>,
    document.body,
  );
}
