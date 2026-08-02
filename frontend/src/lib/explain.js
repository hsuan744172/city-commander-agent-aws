/**
 * 解釋鏈的人話化工具
 *
 * 命題模組 4 要求「清楚展示 AI 的推理過程」，但推理過程要讓指揮官看得懂、
 * 而且要足以判斷 AI 有沒有亂講話。原本的畫面直接倒出模型的原始思考文字、
 * 工具代號與工具回傳的整段 JSON，讀起來像 debug log：資訊量很大，
 * 可驗證性卻很低。
 *
 * 這個模組只做「投影」與「改寫成人話」，不重算任何數值、也不呼叫任何 API。
 * 三層漸進揭露的分工：
 *
 *   第一層 結論與信任訊號   trustStatement()      常駐顯示，一句話講完分工
 *   第二層 人話推理          stepNarrative()       Toggle 展開，因為→依據→所以
 *                            toolNarrative()       查了什麼 → 得到什麼
 *   第三層 原始軌跡          由元件自行巢狀收合，標示「供稽核」
 */

import { toolLabel } from "./aiLabels";

/** 工具回傳摘要在畫面上的長度上限；過長只會變成沒人讀的字串牆。 */
const RESULT_CHAR_LIMIT = 160;

/**
 * 一句話講完「這份判定誰做的」。
 *
 * 後端 decision_trace.engine_split 已經備好 statement，優先採用；
 * 沒有時用步數自行組出同義的句子，畫面不會空著。
 */
export function trustStatement(trace) {
  const split = trace?.engine_split;
  if (!split) return "";
  if (split.statement) return split.statement;

  const rule = split.deterministic || 0;
  const llm = split.llm || 0;
  const total = rule + llm;
  if (total === 0) return "";
  return (
    `${total} 個決策步驟中，${rule} 步為程式確定性運算（門檻、路網篩選、公式），` +
    `${llm} 步由 AI 生成敘述。所有數值皆出自程式，AI 不參與計算。`
  );
}

/**
 * 把一個決策步驟改寫成「因為…，依…，所以…」的人話。
 *
 * 回傳三段而不是一整句：畫面可以把「依據」做成條號徽章、把「所以」做成粗體結論，
 * 不必再從一個長字串裡切。任何一段缺值就留空，呼叫端自行略過。
 */
export function stepNarrative(step) {
  if (!step) return { because: "", basis: "", therefore: "" };

  const inputs = (step.inputs || []).filter((f) => f?.value);
  // 只取前兩個依據數值：一行講得完才有人讀，完整清單在展開區裡
  const because = inputs
    .slice(0, 2)
    .map((f) => `${f.label} ${f.value}`)
    .join("、");

  const articles = step.sop_articles || [];
  const basis = articles.length
    ? `SOP 第 ${articles.join("、")} 條`
    : step.engine === "llm"
      ? "依前述計算結果"
      : "";

  return { because, basis, therefore: step.output || "" };
}

/** 這一步是否還有值得展開的細節（避免畫出一個展開後空白的箭頭）。 */
export function hasStepDetail(step) {
  return Boolean(
    (step?.inputs?.length || 0) > 0 || step?.rule || step?.formula || step?.detail,
  );
}

/**
 * 把工具呼叫改寫成「查了什麼」。
 *
 * 參數名稱本身就是給機器看的，這裡只保留有值的參數並以「鍵 值」呈現，
 * 不輸出 JSON、不用等寬字。
 */
export function toolNarrative(step) {
  const args = Object.entries(step?.input || {}).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );
  const asked = args.map(([key, value]) => `${key} ${value}`).join("、");
  return {
    action: toolLabel(step?.tool),
    asked,
  };
}

/**
 * 工具回傳值的可讀摘要。
 *
 * 後端給的是序列化字串，直接整段貼上會變成畫面上的亂碼牆。這裡把換行與
 * 連續空白收成單行、砍掉最外層的括號雜訊，再截到可讀長度。
 * 完整內容留在第三層原始軌跡裡，需要稽核的人才展開。
 */
export function summarizeToolResult(text) {
  const flat = String(text || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!flat) return "";
  if (flat.length <= RESULT_CHAR_LIMIT) return flat;
  return `${flat.slice(0, RESULT_CHAR_LIMIT).trimEnd()}…`;
}

/**
 * 顧問回覆的「可驗證性」摘要（模組 3）。
 *
 * 回答一個問題：這個答案是查出來的，還是模型自己講的？
 * 依實際呼叫的工具數與引用條文數給出一句話，讓使用者不必自己推敲。
 */
export function verifiabilityNote({ toolsUsed = [], citedClauses = [] } = {}) {
  const tools = toolsUsed.length;
  const clauses = citedClauses.length;

  if (tools === 0 && clauses === 0) {
    return "本次回覆未呼叫計算工具、也未引用條文，請以畫面上的程式判定結果為準。";
  }

  const parts = [];
  if (tools > 0) {
    parts.push(`呼叫 ${tools} 項確定性計算工具取得當下數值`);
  }
  if (clauses > 0) {
    parts.push(`引用 SOP 第 ${citedClauses.map((c) => c.sop_number).join("、")} 條原文`);
  }
  return `本次回覆${parts.join("，並")}；數值與條文均可在下方逐項核對。`;
}

/** AI 敘述來源 → 給使用者看的說法。四處共用同一份措辭。 */
export const NARRATIVE_SOURCE_LABELS = {
  ai_generated: "AI 依程式計算結果生成敘述",
  ai_generated_partial: "AI 生成敘述，現場處置改用程式清單",
  fallback: "AI 未連線，敘述由程式依 SOP 判定結果組出",
  deadline_fallback: "已進入 60 秒時限降級，敘述由程式組出",
};

export function narrativeSourceLabel(source) {
  return NARRATIVE_SOURCE_LABELS[source] || source || "未標示";
}
