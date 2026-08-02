import { createPortal } from "react-dom";

/**
 * 交控中心建議書（列印 / 匯出 PDF）
 *
 * 與 SegmentReport 走同一套機制：以 portal 掛在 document.body 底下的 #print-root，
 * 螢幕上永遠隱藏（樣式見 index.css），只有列印時才顯示，因此不影響事件處置頁版面，
 * 也不需要另開視窗或引入排版套件。
 *
 * 一次可輸出一筆或全部事件，每筆事件獨立一頁（.incident-report-page 的
 * break-after: page），避免「只有第一筆有分析」的誤會。
 *
 * 報告只呈現後端已算好的數值（policy / router / comms / decision_trace），
 * 唯一由語言模型生成的是「AI 決策分析」那一段，且會標注敘述來源。
 */

const CN_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"];

const LANG_NAME = {
  "zh-TW": "繁體中文",
  en: "English",
  ja: "日本語",
  ko: "한국어",
};

const LEVEL_TEXT = {
  A: "A 級（癱瘓）",
  B: "B 級（壅擠）",
  Normal: "正常",
};

const NARRATIVE_SOURCE_TEXT = {
  ai_generated: "語言模型生成（Amazon Bedrock）",
  ai_generated_partial: "語言模型生成，處置條列改用程式依 SOP 組出之清單",
  fallback: "語言模型未連線，改由程式依 SOP 判定結果直述",
  deadline_fallback: "已進入 60 秒時限降級，改由程式依 SOP 判定結果直述",
};

const ROLE_TEXT = {
  primary: "主疏散",
  secondary: "次要",
  excluded: "排除",
};

const CONFORMANCE_STATUS_TEXT = {
  pass: "滿足",
  fail: "未滿足",
  degraded: "退階",
  na: "不適用",
};

function pct(value) {
  if (value == null || value === "") return "無資料";
  return `${Math.round(Number(value) * 100)}%`;
}

function levelText(level) {
  return LEVEL_TEXT[level] || "正常";
}

function has(value) {
  if (value == null) return false;
  if (typeof value === "string") return value.trim() !== "";
  return true;
}

function langLabel(code) {
  return LANG_NAME[code] || code;
}

/** 鍵值表：欄位缺值的列直接不輸出，整表無列時回傳 null，報告不留空殼。 */
function KvTable({ rows, caption }) {
  const filled = (rows || []).filter(([, value]) => has(value));
  if (filled.length === 0) return null;
  return (
    <table className="incident-report-kv">
      {caption && <caption>{caption}</caption>}
      <tbody>
        {filled.map(([label, value]) => (
          <tr key={label}>
            <th scope="row">{label}</th>
            <td>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * 單一事件的建議書頁面。
 *
 * 章節以陣列組出後才編號，因此任何一節被略過都不會留下編號空洞。
 */
function IncidentReportPage({ advisory, generatedAt, indexLabel, totalLabel }) {
  const analysisTime = advisory?.analysis_time || advisory?.generated_at || "";
  const elapsedText =
    advisory?.elapsed_ms != null ? `${(advisory.elapsed_ms / 1000).toFixed(1)} 秒` : "";

  const header = (
    <>
      <header className="incident-report-header">
        <div className="incident-report-agency">臺 北 市 交 通 管 制 中 心</div>
        <h1 className="incident-report-title">交控中心建議書</h1>
        <div className="incident-report-subtitle">
          城市應變指揮官 AI Agent 自動產製　·　突發事件處置（事件注入階段）
        </div>
      </header>

      <table className="incident-report-meta">
        <tbody>
          <tr>
            <th scope="row">事件編號</th>
            <td>{advisory?.event_id || "—"}</td>
            <th scope="row">事件序次</th>
            <td>
              第 {indexLabel} 件
              {totalLabel ? `（本次注入共 ${totalLabel} 件）` : ""}
            </td>
          </tr>
          <tr>
            <th scope="row">分析時間</th>
            <td>{analysisTime || "—"}</td>
            <th scope="row">本事件耗時</th>
            <td>{elapsedText || "—"}</td>
          </tr>
        </tbody>
      </table>
    </>
  );

  if (advisory?.error) {
    return (
      <article className="incident-report incident-report-page">
        {header}
        <section className="incident-report-section incident-report-keep">
          <h2>一、處理結果</h2>
          <KvTable
            rows={[
              ["處理狀態", "異常，未產出完整建議書"],
              ["異常說明", advisory.error],
            ]}
          />
          <p className="incident-report-note">
            本事件於處理過程發生異常，建議書各章節無資料可輸出；請依後端紀錄排除後重新注入。
          </p>
        </section>
        <footer className="incident-report-footer">
          <div>本報告由城市應變指揮官 AI Agent 於 {generatedAt || "—"} 自動產製。</div>
        </footer>
      </article>
    );
  }

  const eid = advisory?.event_identification || {};
  const traffic = advisory?.traffic_classification || {};
  const route = advisory?.route_advisory || {};
  const primary = route.primary_evacuation_route;
  const analysis = route.route_analysis;
  const ete = route.ete_estimate;
  const signals = route.signal_adjustments || [];
  const comms = advisory?.public_communications || {};
  const messages = comms.broadcast_messages || [];
  const crossActions = (advisory?.cross_system_actions || []).filter(
    (action) => action.scope !== "situational",
  );
  const congestion = traffic.congestion_details || [];
  const articles = eid.triggered_sop_articles || [];
  const candidates = analysis?.candidates || primary?.excluded_routes || [];
  const conformance = advisory?.sop_conformance;
  const engineStatement = advisory?.decision_trace?.engine_split?.statement;
  const stations = comms.roaming_trigger_stations || [];

  const incidentSaturation = congestion.find((item) => item.is_incident_segment);
  const affectedParts = [];
  if (has(eid.affected_segment)) affectedParts.push(`受影響路段 ${eid.affected_segment}`);
  if (has(eid.station)) affectedParts.push(`受影響站點 ${eid.station}`);
  if (has(eid.traffic_segment) && eid.traffic_segment !== eid.affected_segment) {
    affectedParts.push(`對應車流路段 ${eid.traffic_segment}`);
  }

  const sections = [];

  // ── 一、事件辨識 ─────────────────────────────────────────
  const hasIdentification = [
    eid.location,
    eid.type,
    eid.status,
    eid.severity,
    eid.description,
    affectedParts.join(""),
  ].some(has);
  const identification = (
    <>
      <KvTable
        rows={[
          ["地點", eid.location],
          ["事件類型", eid.type],
          ["處理狀態", eid.status],
          ["嚴重度", eid.severity],
          ["事件描述", eid.description],
          ["受影響對象", affectedParts.join("；")],
        ]}
      />
      {eid.traffic_segment_source === "affected_road" && has(eid.traffic_segment) && (
        <p className="incident-report-note">
          本事件為人流事件，已依受影響道路對應至車流路段 {eid.traffic_segment}
          ，交通分級判定與預計恢復時間均以該路段之車流量測值計算。
        </p>
      )}
    </>
  );
  if (hasIdentification) {
    sections.push({ title: "事件辨識", body: identification, keep: true });
  }

  // ── 二、交通分級判定 ─────────────────────────────────────
  if (has(traffic.max_level) || congestion.length > 0) {
    sections.push({
      title: "交通分級判定",
      body: (
        <>
          <KvTable
            rows={[
              ["判定級別", `${levelText(traffic.max_level)}`],
              [
                "事件路段",
                has(traffic.incident_segment)
                  ? `${traffic.incident_segment}（飽和度 ${pct(
                      incidentSaturation?.saturation_score,
                    )}，判定 ${levelText(traffic.incident_segment_level)}）`
                  : "",
              ],
              ["全路網最高級別", has(traffic.network_max_level) ? levelText(traffic.network_max_level) : ""],
              [
                "應變觸發路段最高級別",
                has(traffic.trigger_max_level) ? levelText(traffic.trigger_max_level) : "",
              ],
            ]}
          />
          {congestion.length > 0 && (
            <table className="incident-report-table">
              <caption>
                表　全路段車流分級數據佐證（{congestion.length} 段）；分級門檻與判定結果均由程式依
                標準程序第 1 條運算。
              </caption>
              <thead>
                <tr>
                  <th scope="col">路段</th>
                  <th scope="col">飽和度</th>
                  <th scope="col">級別</th>
                  <th scope="col">備註</th>
                </tr>
              </thead>
              <tbody>
                {congestion.map((item) => {
                  const marks = [];
                  if (item.is_incident_segment) marks.push("事件路段");
                  if (item.is_trigger_segment) marks.push("應變觸發路段");
                  return (
                    <tr key={item.segment_id}>
                      <td>{item.road_name || item.segment_id}</td>
                      <td className="num">{pct(item.saturation_score)}</td>
                      <td>{item.description || levelText(item.level)}</td>
                      <td>{marks.join("、") || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </>
      ),
    });
  }

  // ── 三、觸發 SOP 條款 ────────────────────────────────────
  if (articles.length > 0) {
    sections.push({
      title: "本事件觸發之標準程序條款",
      body: (
        <table className="incident-report-table">
          <caption>條款觸發要件由程式逐項比對事件欄位與量測值，語言模型不參與判定。</caption>
          <thead>
            <tr>
              <th scope="col">條號</th>
              <th scope="col">條款名稱</th>
              <th scope="col">觸發理由</th>
            </tr>
          </thead>
          <tbody>
            {articles.map((item) => (
              <tr key={item.sop_number}>
                <td>第 {item.sop_number} 條</td>
                <td>{item.title || "—"}</td>
                <td>{item.reason || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ),
    });
  }

  // ── 四、替代路徑建議 ─────────────────────────────────────
  if (primary) {
    sections.push({
      title: "替代路徑建議",
      body: (
        <>
          <KvTable
            rows={[
              [
                "主疏散路段",
                has(primary.primary_route_name)
                  ? `${primary.primary_route_name}（承載容量 ${
                      primary.capacity_vph ?? "無資料"
                    } 輛/小時，飽和度 ${pct(primary.current_saturation)}）`
                  : "",
              ],
              ["選擇依據", primary.selection_reason],
              [
                "次要疏散路段",
                (primary.secondary_routes || [])
                  .map((item) => `${item.name}（飽和度 ${pct(item.saturation_score)}）`)
                  .join("、"),
              ],
              ["壅塞註記", primary.congestion_note],
              ["上下游判定", analysis?.upstream_resolution?.detail],
            ]}
          />
          {candidates.length > 0 && (
            <table className="incident-report-table">
              <caption>
                表　候選替代道路評估（{candidates.length} 條，含排除理由）；容量下限與相交、
                上游條件依標準程序第 2 條。
              </caption>
              <thead>
                <tr>
                  <th scope="col">判定</th>
                  <th scope="col">候選路段</th>
                  <th scope="col">承載容量</th>
                  <th scope="col">飽和度</th>
                  <th scope="col">理由</th>
                </tr>
              </thead>
              <tbody>
                {[...candidates]
                  .sort((a, b) => {
                    const order = { primary: 0, secondary: 1, excluded: 2 };
                    return (order[a.role] ?? 3) - (order[b.role] ?? 3);
                  })
                  .map((item) => (
                    <tr key={item.segment_id || item.name}>
                      <td>{ROLE_TEXT[item.role] || "排除"}</td>
                      <td>{item.name || item.segment_id}</td>
                      <td className="num">
                        {item.capacity_vph != null ? `${item.capacity_vph} 輛/小時` : "無資料"}
                      </td>
                      <td className="num">{pct(item.saturation_score)}</td>
                      <td>{item.reason || "—"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </>
      ),
    });
  }

  // ── 五、號誌調整建議 ─────────────────────────────────────
  if (signals.length > 0) {
    sections.push({
      title: "號誌調整建議",
      body: (
        <table className="incident-report-table">
          <caption>依標準程序第 1 條對替代道路實施長綠燈時制。</caption>
          <thead>
            <tr>
              <th scope="col">調整路段</th>
              <th scope="col">調整內容</th>
              <th scope="col">實施時段</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((item, index) => (
              <tr key={`${item.segment_id || item.road_name}-${index}`}>
                <td>{item.road_name || item.segment_id}</td>
                <td>{item.action || "—"}</td>
                <td>{item.window || "依現場滾動調整"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ),
    });
  }

  // ── 六、預計恢復時間 ─────────────────────────────────────
  if (ete) {
    sections.push({
      title: "預計交通恢復時間",
      body: (
        <KvTable
          caption="依標準程序第 7 條公式計算，所有取值均由程式運算。"
          rows={[
            ["計算公式", ete.formula],
            [
              "基礎清除時間",
              has(ete.base_clearance_minutes)
                ? `${ete.base_clearance_minutes} 分鐘${
                    has(ete.severity) ? `（嚴重度 ${ete.severity}）` : ""
                  }`
                : "",
            ],
            [
              "壅塞懲罰時間",
              has(ete.congestion_penalty_minutes)
                ? `${ete.congestion_penalty_minutes} 分鐘${
                    ete.avg_saturation_score != null
                      ? `（受影響路段平均飽和度 ${pct(ete.avg_saturation_score)}）`
                      : ""
                  }`
                : "",
            ],
            [
              "納入計算路段",
              (ete.affected_segments || [])
                .map((item) =>
                  item.available
                    ? `${item.road_name || item.segment_id} ${pct(item.saturation_score)}`
                    : `${item.segment_id}（無車流資料）`,
                )
                .join("、") || ete.affected_segments_definition,
            ],
            [
              "預計恢復時間",
              has(ete.ete_minutes) ? `${ete.ete_minutes} 分鐘` : "",
            ],
            ["註記", ete.note],
          ]}
        />
      ),
    });
  }

  // ── 七、跨系統聯動 ───────────────────────────────────────
  if (crossActions.length > 0) {
    sections.push({
      title: "跨系統聯動請求",
      body: (
        <table className="incident-report-table">
          <caption>受文單位與請求事項由程式依觸發條款產出，條號為依據來源。</caption>
          <thead>
            <tr>
              <th scope="col">受文單位</th>
              <th scope="col">請求事項</th>
              <th scope="col">條號依據</th>
            </tr>
          </thead>
          <tbody>
            {crossActions.map((item, index) => (
              <tr key={`${item.agency}-${index}`}>
                <td>{item.agency || "—"}</td>
                <td>
                  {item.request || "—"}
                  {has(item.basis) && (
                    <span className="incident-report-inline-note">依據：{item.basis}</span>
                  )}
                </td>
                <td>{item.sop_reference || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ),
    });
  }

  // ── 八、多語化民眾簡訊 ───────────────────────────────────
  if (messages.length > 0) {
    sections.push({
      title: "多語化民眾通報簡訊",
      body: (
        <>
          <p>
            本事件通報語言共 {messages.length} 種：
            {messages.map((item) => langLabel(item.language)).join("、")}。
            {comms.trigger_multilingual_sop6
              ? "已觸發標準程序第 6 條多語通報要求。"
              : "未達標準程序第 6 條漫遊門檻，依條文僅需繁體中文。"}
          </p>
          {comms.trigger_multilingual_sop6 && stations.length > 0 && (
            <p className="incident-report-note">
              第 6 條達標站點（判定範圍：{comms.roaming_scope || "全資料集所有基地台"}）：
              {stations
                .map(
                  (item) =>
                    `${item.location_name || item.bs_id} ${item.roaming_user_pct_display || ""}`.trim(),
                )
                .join("、")}
            </p>
          )}
          <dl className="incident-report-messages">
            {messages.map((item) => (
              <div key={item.language} className="incident-report-message incident-report-keep">
                <dt>
                  {langLabel(item.language)}
                  <span className="incident-report-lang-code">（{item.language}）</span>
                </dt>
                <dd>{item.sms_text || item.message || item.cms_text || "—"}</dd>
              </div>
            ))}
          </dl>
        </>
      ),
    });
  }

  // ── 九、AI 決策分析 ──────────────────────────────────────
  if (has(advisory?.ai_narrative)) {
    sections.push({
      title: "AI 決策分析",
      body: (
        <>
          <div className="incident-report-narrative">
            {String(advisory.ai_narrative)
              .split(/\n+/)
              .filter(Boolean)
              .map((paragraph, index) => (
                <p key={index}>{paragraph}</p>
              ))}
          </div>
          <p className="incident-report-note">
            敘述來源：
            {NARRATIVE_SOURCE_TEXT[advisory.ai_narrative_source] ||
              advisory.ai_narrative_source ||
              "未標示"}
            。分級門檻、路網篩選與所有公式運算均由程式完成，語言模型不參與判定。
          </p>
        </>
      ),
    });
  }

  // ── 十、決策鏈與合規檢核 ─────────────────────────────────
  if (has(engineStatement) || conformance) {
    const failedChecks = (conformance?.articles || []).flatMap((article) =>
      (article.checks || [])
        .filter((check) => check.status === "fail")
        .map((check) => ({
          key: `${article.sop_number}-${check.requirement}`,
          text: `第 ${article.sop_number} 條 ${check.clause || ""} ${check.requirement}`.trim(),
          evidence: check.evidence,
        })),
    );
    sections.push({
      title: "決策鏈與合規檢核",
      body: (
        <>
          <KvTable
            rows={[
              ["決策分工", engineStatement],
              [
                "合規檢核結果",
                conformance
                  ? `${conformance.satisfied_checks}/${conformance.total_checks} 項滿足${
                      conformance.degraded_checks
                        ? `，其中 ${conformance.degraded_checks} 項為條文允許之退階`
                        : ""
                    }${conformance.failed_checks ? `，${conformance.failed_checks} 項未滿足` : "，無未滿足項目"}`
                  : "",
              ],
              [
                "本事件主條款",
                (conformance?.primary_articles || []).map((n) => `第 ${n} 條`).join("、"),
              ],
            ]}
          />
          {failedChecks.length > 0 && (
            <table className="incident-report-table">
              <caption>未滿足之檢核項目（需人工介入）</caption>
              <thead>
                <tr>
                  <th scope="col">檢核項目</th>
                  <th scope="col">狀態</th>
                  <th scope="col">佐證</th>
                </tr>
              </thead>
              <tbody>
                {failedChecks.map((item) => (
                  <tr key={item.key}>
                    <td>{item.text}</td>
                    <td>{CONFORMANCE_STATUS_TEXT.fail}</td>
                    <td>{item.evidence || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      ),
    });
  }

  return (
    <article className="incident-report incident-report-page">
      {header}
      {sections.map((section, index) => (
        <section
          key={section.title}
          className={
            section.keep
              ? "incident-report-section incident-report-keep"
              : "incident-report-section"
          }
        >
          <h2>
            {CN_NUM[index] || index + 1}、{section.title}
          </h2>
          {section.body}
        </section>
      ))}
      <footer className="incident-report-footer">
        <div>
          本建議書由城市應變指揮官 AI Agent 於 {generatedAt || "—"} 自動產製
          {analysisTime ? `，內容依據分析時間 ${analysisTime} 之路網量測值` : ""}。
        </div>
        <div>
          資料來源：city_traffic_flow.csv（路段車流與飽和度）、road_network_geometry.json
          （路網拓樸與承載容量）、signaling_crowd_density.csv（人流與信令）、
          emergency_traffic_sop.txt（交通應變標準程序）。
        </div>
      </footer>
    </article>
  );
}

/**
 * pages：[{ advisory, seq, total }]，seq 是該事件在本次注入中的序次，
 * total 是本次注入的事件總數。單事件匯出時序次仍維持原本的第幾件，
 * 讀報告的人不會誤以為只注入了一件。
 */
export default function IncidentReport({ pages = [], generatedAt = "" }) {
  if (pages.length === 0) return null;

  return createPortal(
    <div id="print-root">
      {pages.map((page, index) => (
        <IncidentReportPage
          key={page.advisory?.event_id || index}
          advisory={page.advisory}
          generatedAt={generatedAt}
          indexLabel={page.seq ?? index + 1}
          totalLabel={page.total ?? pages.length}
        />
      ))}
    </div>,
    document.body,
  );
}
