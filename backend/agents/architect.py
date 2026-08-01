"""
Architect Commander Agent — 總指揮 (FastAPI 同 process 版)。

協調 Policy / Router / Comms，彙整交控中心建議書，並提供 What-if 對話顧問與
儀表板預警摘要。

分工紀律：
  - 事件分類只在 sop_rules.classify_incident
  - 門檻與規則常數只在 sop_rules
  - 數值計算只在 traffic_math
  - 這裡只做流程協調、跨單位處置組裝、以及 LLM 敘述生成
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from backend import sim_clock
from backend.agents import policy, sop_rules, traffic_math
from backend.agents.comms import run_comms
from backend.agents.policy import evaluate_data_triggers, run_assessment
from backend.agents.router import run_routing

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
# Incident events are uploaded by the operator, not pulled from S3. This local
# file is only the sample used when no payload is supplied with the request.
LIVE_INCIDENTS_FILE = DATA_DIR / "live_incidents.json"

# Output-token cap and sampling settings for every Bedrock call.
#
# The advisory prompt asks for three paragraphs (<= 450 Chinese characters) plus a
# four-line field-action list, and Chinese runs close to one token per character.
# 900 tokens was too tight: Bedrock raised MaxTokensReachedException mid-generation
# and the whole advisory silently fell back to the deterministic narrative.
# 1500 leaves headroom while still bounding worst-case latency inside the 60s budget.
BEDROCK_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "1500"))
BEDROCK_TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.2"))

# The foundation model admits roughly one request per second, so calls are spaced
# by a token bucket instead of being serialised behind each other's latency.
# Incidents are then processed concurrently, which keeps a multi-event batch
# inside the 60-second demo budget without ever exceeding the request rate.
BEDROCK_MIN_CALL_INTERVAL = float(os.environ.get("BEDROCK_MIN_CALL_INTERVAL", "1.1"))
INCIDENT_MAX_WORKERS = int(os.environ.get("INCIDENT_MAX_WORKERS", "4"))

# 對話顧問保留的往返輪數，避免 context 無限增長
CHAT_HISTORY_TURNS = int(os.environ.get("CHAT_HISTORY_TURNS", "8"))

NARRATIVE_CHAR_LIMIT = 450
NARRATIVE_HARD_LIMIT = 500


class _CallRateLimiter:
    """Serialise only the *start* of each call, keeping a minimum interval."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


_bedrock_rate_limiter = _CallRateLimiter(BEDROCK_MIN_CALL_INTERVAL)


# ---------------------------------------------------------------------------
# 資料載入
# ---------------------------------------------------------------------------


def _load_incidents(event: dict | None = None) -> list[dict]:
    if event and isinstance(event, dict) and "incidents" in event:
        incidents = event["incidents"]
        return incidents if isinstance(incidents, list) else []
    if LIVE_INCIDENTS_FILE.exists():
        with open(LIVE_INCIDENTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def _load_traffic_data(timestamp: str | None = None) -> dict:
    """
    截至查詢時間的路網狀態。timestamp 為空時由模擬時鐘決定當下時間。
    切片邏輯統一交給 traffic_math._get_time_slice，避免多份重複實作。
    """
    import pandas as pd

    from backend.agents.traffic_math import _get_time_slice, _load_traffic_flow

    time_df, _ = _get_time_slice(_load_traffic_flow(), timestamp, key_col="Segment_ID")

    result = {}
    for _, row in time_df.iterrows():
        result[row["Segment_ID"]] = {
            "road_name": row["Road_Name"],
            "saturation_score": float(row["Saturation_Score"]),
            "avg_speed": float(row["Avg_Speed"]),
            "vehicle_count": int(row["Vehicle_Count"]),
            "lane_status": row["Lane_Status"],
            "data_as_of": pd.Timestamp(row["Timestamp"]).strftime(sim_clock.TIME_FMT),
        }
    return result


def _nearby_stations(segment_id: str) -> list[str]:
    return list(traffic_math.segment_info(segment_id).get("nearby_stations") or [])


# ---------------------------------------------------------------------------
# 跨系統聯動 — 交付要求「觸發第 3 或第 5 條時列出對北捷、公車處、警力之請求」
# ---------------------------------------------------------------------------

AGENCY_MRT = "臺北捷運公司"
AGENCY_BUS = "公車處"
AGENCY_POLICE = "警察局交通警察大隊"
AGENCY_TCC = "交控中心"
AGENCY_VENUE = "臺北大巨蛋場館管理單位"


def _cross_system_actions(policy_result: dict, routing_result: dict) -> list[dict]:
    """
    由 SOP 判定結果推導跨單位請求。刻意做成確定性清單，不依賴 LLM：
    評審會逐項對照條文，這裡每一筆都標明條號與依據數值。
    """
    actions: list[dict] = []
    checks = {c["sop_number"]: c for c in policy_result.get("triggered_sops", [])}

    def scope_of(sop_number: int) -> str:
        return (checks.get(sop_number) or {}).get("scope", policy.SCOPE_SITUATIONAL)

    sop4 = checks.get(4) or {}
    if sop4.get("triggered"):
        evidence = sop4.get("evidence", {})
        basis = (
            f"歷史峰值 {evidence.get('peak_user_count', 0):,} 人"
            f"（{evidence.get('peak_at', '')}）、當前人流增幅 "
            f"{float(evidence.get('current_growth_rate', 0)):.0%}"
        )
        actions.append({
            "agency": AGENCY_VENUE,
            "request": "確認散場已啟動，回報場館內剩餘人數與出場動線分配",
            "sop_reference": "SOP 第 4 條",
            "basis": basis,
        })
        actions.append({
            "agency": AGENCY_BUS,
            "request": "依第 4 條提前連動第 3 條，預先備援接駁專車待命",
            "sop_reference": "SOP 第 4 條連動第 3 條",
            "basis": basis,
        })

    sop3 = checks.get(3) or {}
    if sop3.get("triggered"):
        evidence = sop3.get("evidence", {})
        basis = (
            f"{evidence.get('location_name', sop_rules.SOP3_STATION)} 人數 "
            f"{int(evidence.get('user_count', 0)):,} 人、人流增幅 "
            f"{float(evidence.get('growth_rate', 0)):.0%}"
        )
        actions.extend([
            {
                "agency": AGENCY_MRT,
                "request": "國父紀念館站 (BL17) 啟動過站不停，並加開往市政府站區間車",
                "sop_reference": "SOP 第 3 條",
                "basis": basis,
            },
            {
                "agency": AGENCY_BUS,
                "request": "調度接駁專車疏運滯留人潮",
                "sop_reference": "SOP 第 3 條",
                "basis": basis,
            },
            {
                "agency": AGENCY_POLICE,
                "request": "派員引導群眾步行至市政府站 (BL18) 分流並維持站體秩序",
                "sop_reference": "SOP 第 3 條",
                "basis": basis,
            },
        ])
    elif sop3.get("cascaded_from") == 4:
        actions.append({
            "agency": AGENCY_MRT,
            "request": "預先評估國父紀念館站過站不停時機，人流門檻達標即啟動",
            "sop_reference": "SOP 第 4 條連動第 3 條",
            "basis": sop3.get("reason", ""),
        })

    sop5 = checks.get(5) or {}
    if sop5.get("triggered"):
        segment_id = routing_result.get("incident_segment_id", "")
        intersections = list(traffic_math.segment_info(segment_id).get("intersections") or [])
        officers = sop_rules.police_required(len(intersections))
        ete = (routing_result.get("ete_result") or {}).get("ete_minutes")
        actions.append({
            "agency": AGENCY_POLICE,
            "request": (
                f"派遣 {officers} 名警力（每路口 "
                f"{sop_rules.SOP5_POLICE_PER_INTERSECTION} 人）至"
                f"{'、'.join(intersections) if intersections else '受影響路口'}執行人工指揮"
            ),
            "sop_reference": "SOP 第 5 條",
            "basis": (
                f"{routing_result.get('incident_name', segment_id)} 號誌失效，"
                f"{len(intersections)} 處相交路口，預計 {ete} 分鐘內恢復"
                if ete
                else f"{routing_result.get('incident_name', segment_id)} 號誌失效"
            ),
        })
        actions.append({
            "agency": AGENCY_TCC,
            "request": "監控號誌設備修復進度，恢復後回報並解除人工指揮",
            "sop_reference": "SOP 第 5 條",
            "basis": "號誌故障應變需追蹤修復狀態",
        })

    # SOP 第 1 條：觸發路段達級別 → 長綠燈時制 + 警力淨空路口
    for plan in routing_result.get("signal_plans", []):
        if plan.get("scope") != traffic_math.SIGNAL_SCOPE_SOP1:
            continue
        roads = "、".join(a["road_name"] for a in plan.get("adjustments", []))
        actions.append({
            "agency": AGENCY_TCC,
            "request": (
                f"{plan['road_name']}達 {plan['level_description']}，"
                f"{roads} 綠燈配時 +{sop_rules.GREEN_LIGHT_EXTENSION_PCT}%"
                f"（{plan.get('window') or '時段依現場滾動調整'}）"
            ),
            "sop_reference": "SOP 第 1 條",
            "basis": f"飽和度 {round(float(plan.get('saturation_score') or 0) * 100)}%",
        })
        dispatch = plan.get("police_dispatch") or {}
        if dispatch.get("officers"):
            actions.append({
                "agency": AGENCY_POLICE,
                "request": f"{dispatch['instruction']}，共 {dispatch['officers']} 名警力",
                "sop_reference": "SOP 第 1 條",
                "basis": f"{plan['road_name']}達 {plan['level_description']}",
            })

    sop6 = checks.get(6) or {}
    if sop6.get("triggered"):
        stations = (sop6.get("evidence") or {}).get("trigger_stations") or []
        detail = "、".join(
            f"{s['location_name']} {s['roaming_user_pct_display']}" for s in stations
        )
        actions.append({
            "agency": AGENCY_TCC,
            "request": "簡訊與 CMS 看板同步發布繁中／英／日／韓四語版本",
            "sop_reference": "SOP 第 6 條",
            "basis": f"漫遊率達標站點：{detail}",
        })

    # 標記每一筆請求屬於「本事件處置」還是「全市態勢」，前端可分區呈現
    for action in actions:
        match = re.search(r"第\s*([1-7])\s*條", action.get("sop_reference", ""))
        number = int(match.group(1)) if match else 0
        action["scope"] = policy.SCOPE_EVENT if number == 1 else scope_of(number)

    return actions


# ---------------------------------------------------------------------------
# 單一事件處理
# ---------------------------------------------------------------------------


def _process_incident(incident: dict, triggers_for=None, allow_ai: bool = True) -> dict:
    """
    處理單一事件。

    triggers_for：以時間為 key 取得資料型 SOP 判定的函式（批次處理時共用同一份，
    同一時間點不重算）。留空則直接計算。
    """
    if not incident or not isinstance(incident, dict):
        return {"event_id": "UNKNOWN", "error": "Invalid incident", "status": "failed"}

    started = time.monotonic()
    event_id = incident.get("event_id") or "UNKNOWN"
    # 事件未帶時間 → 視為「當下」發生，交由模擬時鐘決定
    timestamp = sim_clock.resolve(incident.get("timestamp")).strftime(sim_clock.TIME_FMT)
    info = sop_rules.classify_incident(incident)

    # 資料型 SOP（第 3、4、6 條）只依時間而定，同一時間的事件共用結果
    data_triggers = (triggers_for or evaluate_data_triggers)(timestamp)

    # Phase 1: Policy
    traffic_data = _load_traffic_data(timestamp)
    policy_result = run_assessment({
        "incident": incident,
        "classification": info,
        "traffic_data": traffic_data,
        "data_triggers": data_triggers,
        "timestamp": timestamp,
    })
    policy_result = policy_result if isinstance(policy_result, dict) else {}

    # Phase 2: Routing + ETE + 號誌配時（所有事件走同一條路徑，不再各自算 ETE）
    routing_result = run_routing({
        "incident": incident,
        "classification": info,
        "timestamp": timestamp,
    })
    routing_result = routing_result if isinstance(routing_result, dict) else {}

    # Phase 3: Comms（SOP 第 6 條觸發判定由 policy 的全市掃描決定）
    nearby = _nearby_stations(info.traffic_segment or info.affected_segment)
    if info.station and info.station not in nearby:
        nearby.append(info.station)

    comms_result = run_comms({
        "incident": incident,
        "classification": info,
        "routing_result": routing_result,
        "sop6": data_triggers["sop6"],
        "nearby_stations": nearby,
        "timestamp": timestamp,
    })
    comms_result = comms_result if isinstance(comms_result, dict) else {}

    # Phase 4: 跨系統聯動（確定性）
    cross_actions = _cross_system_actions(policy_result, routing_result)

    # Phase 5: AI 建議書敘述 + 現場處置條列。若已進入時限降級，直接使用
    # 確定性 SOP 結果，避免模型延遲阻擋 60 秒事件處置預算。
    if allow_ai:
        ai = _generate_advisory_ai(
            incident, info, policy_result, routing_result, comms_result, cross_actions
        )
    else:
        ai = {
            "narrative": _deterministic_narrative(incident, policy_result, routing_result),
            "actions": _fallback_actions(info, policy_result, routing_result),
            "title": _advisory_title(info),
            "source": "deadline_fallback",
        }

    advisory = _assemble_advisory(
        incident, info, policy_result, routing_result, comms_result,
        cross_actions, timestamp,
    )
    advisory["ai_narrative"] = ai["narrative"]
    advisory["ai_narrative_source"] = ai["source"]
    if ai["actions"]:
        advisory["field_actions"] = {
            "title": ai["title"],
            "actions": ai["actions"],
            "source": ai["source"],
        }
    advisory["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return advisory


def _advisory_title(info) -> str:
    if info.is_signal_failure:
        return "號誌故障人工指揮派遣方案"
    if info.is_crowd:
        return "捷運與接駁分流處置方案"
    return "事故現場疏導處置方案"


def _fallback_actions(info, policy_result: dict, routing_result: dict) -> list[str]:
    """
    Bedrock 不可用時的處置條列。全部由 SOP 判定結果直接組出，不含推測。
    只取與本事件相關的條款，否則號誌故障的現場處置會冒出捷運分流動作。
    """
    actions: list[str] = []
    for check in policy_result.get("triggered_sops", []):
        if check.get("triggered") and check.get("scope") == policy.SCOPE_EVENT:
            actions.extend(check.get("actions", []))
    route = routing_result.get("route_recommendation") or {}
    if route.get("primary_route_name"):
        actions.insert(0, f"引導車流改道 {route['primary_route_name']}")
    ete = (routing_result.get("ete_result") or {}).get("ete_minutes")
    if ete:
        actions.append(f"預計 {int(round(float(ete)))} 分鐘恢復，屆時重新評估")
    return actions[:8]


def _generate_advisory_ai(
    incident: dict,
    info,
    policy_result: dict,
    routing_result: dict,
    comms_result: dict,
    cross_actions: list[dict],
) -> dict:
    """
    透過 Amazon Bedrock Claude 產出建議書敘述與現場處置條列。

    原本分兩次呼叫（特殊處置 + 建議書敘述），這裡合併成一次：
    3 件事件的 Bedrock 呼叫數由 5 次降到 3 次，也少一個失敗點。
    """
    title = _advisory_title(info)
    fallback_actions = _fallback_actions(info, policy_result, routing_result)

    sop_clauses = policy_result.get("sop_clauses") or []
    clause_text = "\n\n".join(f"{c['text']}" for c in sop_clauses)[:4000]

    route_rec = routing_result.get("route_recommendation") or {}
    ete = routing_result.get("ete_result") or {}

    facts: list[str] = [
        f"事件 {incident.get('event_id')}：{incident.get('description', '')}",
        f"位置：{incident.get('location', '')}",
        f"狀態：{incident.get('status', '')}，嚴重度：{incident.get('severity', '')}",
        f"事件時間：{incident.get('timestamp', '')}",
        f"交通分級：{policy_result.get('max_level', 'Normal')}"
        f"（{sop_rules.level_description(policy_result.get('max_level', 'Normal'))}）",
        f"判定摘要：{policy_result.get('summary', '')}",
    ]
    if route_rec:
        facts.append(
            f"主疏散路徑：{route_rec.get('primary_route_name', '')}"
            f"（容量 {route_rec.get('capacity_vph', 0)} 車/小時，飽和度 "
            f"{round(float(route_rec.get('current_saturation') or 0) * 100)}%）"
        )
        facts.append(f"選擇依據：{route_rec.get('selection_reason', '')}")
        secondary = "、".join(r.get("name", "") for r in route_rec.get("secondary_routes", []))
        if secondary:
            facts.append(f"次要疏散：{secondary}")
        excluded = "；".join(
            f"{r.get('name', '')}（{r.get('reason', '')}）"
            for r in route_rec.get("excluded_routes", [])
        )
        if excluded:
            facts.append(f"排除候選：{excluded}")
        if route_rec.get("congestion_note"):
            facts.append(route_rec["congestion_note"])
    if ete:
        facts.append(
            f"ETE：{ete.get('ete_minutes')} 分鐘"
            f"（基礎清除 {ete.get('base_clearance_minutes')} + 壅塞懲罰 "
            f"{ete.get('congestion_penalty_minutes')}）"
            + (f"；{ete.get('note')}" if ete.get("note") else "")
        )
    for plan in routing_result.get("signal_plans", []):
        roads = "、".join(a["road_name"] for a in plan.get("adjustments", []))
        if roads:
            facts.append(
                f"號誌配時：{roads} 綠燈 +{sop_rules.GREEN_LIGHT_EXTENSION_PCT}%，"
                f"{plan.get('window') or '時段依現場調整'}"
            )
    if cross_actions:
        facts.append(
            "跨單位請求："
            + "；".join(f"{a['agency']}—{a['request']}" for a in cross_actions)
        )
    if comms_result.get("messages"):
        langs = "、".join(m["language"] for m in comms_result["messages"])
        facts.append(
            f"通報語言：{langs}"
            + ("（SOP 第 6 條多語觸發）" if comms_result.get("trigger_sop6") else "")
        )

    facts_text = "\n".join(f"- {line}" for line in facts if line and line.strip("- "))

    prompt = f"""你是台北市交控中心的 AI 決策顧問。根據以下已完成的計算結果與 SOP 條文，撰寫一份正式的「交控中心建議書」。

【計算結果】
{facts_text}

【SOP 條文原文】
{clause_text}

【輸出格式，務必逐字遵守】
第一段以「判斷：」開頭
第二段以「建議：」開頭
第三段以「行動指令：」開頭
第四段以「現場處置：」開頭，之後每行一項具體處置，以「・」起頭，共 4 行

【硬性規則】
- 前三段合計不得超過 {NARRATIVE_CHAR_LIMIT} 個中文字，每段最多三句
- 現場處置每行 15 到 25 字，只列最關鍵的 4 項
- 只能使用上列計算結果與 SOP 條文中的數字，不得自行新增任何數值、時間間隔、人力或百分比
- 引用條款時標明條號，例如「依 SOP 第 2 條」
- 時間一律 YYYY-MM-DD HH:MM
- 不使用 Markdown 標題、粗體、表格、分隔線、LaTeX 或程式碼區塊
- 不輸出英文欄位名稱或路段代碼，數值用自然中文（例如「飽和度 95%」）
"""

    system_prompt = (
        "你是台北市交控中心 AI 決策顧問。只可依提供的 SOP 條文與計算結果作答，"
        "禁止自行推算或補充任何數字。輸出四段純文字：判斷、建議、行動指令、現場處置。"
    )

    try:
        result = _call_bedrock(prompt, system_prompt, "advisory")
        if not result.get("ok"):
            raise RuntimeError(f"bedrock unavailable ({result.get('fallback_reason')})")
        narrative, actions = _split_advisory_response(result.get("response", ""))
        if not narrative:
            raise RuntimeError("empty narrative")
        return {
            "narrative": narrative,
            "actions": actions or fallback_actions,
            "title": title,
            "source": "ai_generated" if actions else "ai_generated_partial",
        }
    except Exception as exc:
        logger.error(f"AI 建議書生成失敗，改用 SOP 確定性敘述: {exc}")
        return {
            "narrative": _deterministic_narrative(incident, policy_result, routing_result),
            "actions": fallback_actions,
            "title": title,
            "source": "fallback",
        }


_FIELD_ACTION_MARKER = re.compile(r"^\s*(?:現場處置|現場處置：|現場處置:)\s*", re.MULTILINE)
_BULLET_PREFIX = "0123456789.、-•·・）) 　"


def _split_advisory_response(response: str) -> tuple[str, list[str]]:
    """把單次回應切成「敘述三段」與「現場處置條列」。"""
    text = _sanitize_ai_text(response)
    if not text:
        return "", []

    match = _FIELD_ACTION_MARKER.search(text)
    if not match:
        return _limit_narrative(text), []

    narrative = _limit_narrative(text[: match.start()].strip())
    actions = []
    for line in text[match.end():].splitlines():
        cleaned = line.strip().lstrip(_BULLET_PREFIX).strip()
        if len(cleaned) >= 6:
            actions.append(cleaned)
    return narrative, actions[:8]


def _sanitize_ai_text(response: str) -> str:
    text = response or ""
    for forbidden in ("```", "**", "###", "##", "$", "\\frac", "Saturation_Score", "capacity_vph"):
        text = text.replace(forbidden, "")
    return text.strip()


def _limit_narrative(text: str) -> str:
    """
    上限保護。改成優先在句末截斷，找不到句末才硬切，
    並在硬切時補上刪節號，避免畫面出現斷在半句的敘述。
    """
    text = (text or "").strip()
    if len(text) <= NARRATIVE_HARD_LIMIT:
        return text
    shortened = text[:NARRATIVE_HARD_LIMIT]
    boundary = max(shortened.rfind(mark) for mark in ("。", "！", "？", "\n"))
    if boundary >= NARRATIVE_CHAR_LIMIT * 0.6:
        return shortened[: boundary + 1].strip()
    return shortened.rstrip() + "…"


def _deterministic_narrative(incident: dict, policy_result: dict, routing_result: dict) -> str:
    """Bedrock 不可用時的建議書敘述。只重述已計算的事實。"""
    location = incident.get("location") or "受影響區域"
    level = policy_result.get("max_level", "Normal")
    route = routing_result.get("route_recommendation") or {}
    ete = (routing_result.get("ete_result") or {}).get("ete_minutes")
    numbers = [f"第 {n} 條" for n in policy_result.get("event_sop_numbers", [])]
    description = incident.get("description") or "事件已受理"

    judgement = (
        f"判斷：{location}—{description}；"
        f"依 SOP 第 1 條判定為 {sop_rules.level_description(level)}"
        + (f"，觸發 SOP {'、'.join(numbers)}" if numbers else "")
        + "。"
    )
    if route.get("primary_route_name"):
        suggestion = (
            f"建議：車流改道 {route['primary_route_name']}，"
            f"{route.get('selection_reason', '')}。"
        )
    else:
        # 無替代路徑重規劃時（人流事件、號誌故障），改用該事件觸發條款的處置
        event_actions = [
            action
            for check in policy_result.get("triggered_sops", [])
            if check.get("triggered") and check.get("scope") == policy.SCOPE_EVENT
            for action in check.get("actions", [])
        ]
        suggestion = "建議：" + (
            "；".join(event_actions[:3]) + "。"
            if event_actions
            else "維持現行動線並持續監控路網狀態。"
        )
    order = "行動指令：" + (
        f"立即執行建議書所列號誌、疏導及跨單位協調措施，預計 {int(round(float(ete)))} 分鐘後重新評估。"
        if ete
        else "立即執行建議書所列號誌、疏導及跨單位協調措施。"
    )
    return "\n".join([judgement, suggestion, order])


def _assemble_advisory(
    incident: dict,
    info,
    policy_result: dict,
    routing_result: dict,
    comms_result: dict,
    cross_actions: list[dict],
    timestamp: str,
) -> dict:
    incident = incident if isinstance(incident, dict) else {}
    policy_result = policy_result if isinstance(policy_result, dict) else {}
    routing_result = routing_result if isinstance(routing_result, dict) else {}
    comms_result = comms_result if isinstance(comms_result, dict) else {}

    event_id = incident.get("event_id", "UNKNOWN")
    triggered = [
        s for s in policy_result.get("triggered_sops", [])
        if isinstance(s, dict) and s.get("triggered")
    ]

    def article(check: dict) -> dict:
        return {
            "sop_number": check["sop_number"],
            "title": check["sop_title"],
            "reason": check["reason"],
            "evidence": check.get("evidence", {}),
            "actions": check.get("actions", []),
        }

    event_articles = [article(s) for s in triggered if s.get("scope") == policy.SCOPE_EVENT]
    situational_articles = [
        article(s) for s in triggered if s.get("scope") == policy.SCOPE_SITUATIONAL
    ]

    return {
        "advisory_type": "交控中心建議書",
        # 建議書所依據的情境時間就是事件的分析時間，兩者不再各走一套時鐘
        "generated_at": timestamp,
        "analysis_time": timestamp,
        "sim_time": sim_clock.now_str(),
        "real_generated_at": datetime.now().strftime(sim_clock.TIME_FMT),
        "event_id": event_id,
        "event_timestamp": timestamp,
        "event_identification": {
            "event_id": event_id,
            "type": incident.get("type", ""),
            "kind": info.kind,
            "location": incident.get("location", ""),
            "affected_segment": info.affected_segment,
            "traffic_segment": info.traffic_segment,
            "traffic_segment_source": info.traffic_segment_source,
            "station": info.station,
            "status": incident.get("status", ""),
            "severity": incident.get("severity", ""),
            "description": incident.get("description", ""),
            # 本事件觸發的條款
            "triggered_sop_articles": event_articles,
        },
        # 同一時間全市資料同時符合的條款（例如大巨蛋散場、多語通報門檻），
        # 與本事件不是因果關係，另外分開列，避免建議書讀起來張冠李戴
        "situational_sop_articles": situational_articles,
        "traffic_classification": {
            "max_level": policy_result.get("max_level", "Normal"),
            "incident_segment_level": policy_result.get("incident_segment_level"),
            "incident_segment": policy_result.get("incident_segment", ""),
            "network_max_level": policy_result.get("network_max_level", "Normal"),
            "trigger_max_level": policy_result.get("trigger_max_level", "Normal"),
            "trigger_segment_levels": policy_result.get("trigger_segment_levels", []),
            "congestion_details": policy_result.get("congestion_levels", []),
        },
        "route_advisory": {
            "primary_evacuation_route": routing_result.get("route_recommendation"),
            "ete_estimate": routing_result.get("ete_result"),
            "route_analysis": routing_result.get("route_analysis"),
            "navigation_update": routing_result.get("navigation_update", {}),
            "signal_plans": routing_result.get("signal_plans", []),
            "signal_adjustments": routing_result.get("signal_suggestions", []),
        },
        "cross_system_actions": cross_actions,
        "public_communications": {
            "trigger_multilingual_sop6": comms_result.get("trigger_sop6", False),
            "roaming_scope": comms_result.get("roaming_scope", ""),
            "roaming_trigger_stations": comms_result.get("trigger_stations", []),
            "nearby_station_checks": comms_result.get("nearby_station_checks", []),
            "roaming_checks": comms_result.get("roaming_checks", []),
            "languages": comms_result.get("languages", []),
            "broadcast_messages": comms_result.get("messages", []),
            "cms_broadcast": comms_result.get("cms_broadcast", {}),
            "message_requirements": comms_result.get("message_requirements", {}),
        },
        "sop_clauses": policy_result.get("sop_clauses", []),
        "summary": policy_result.get("summary", ""),
        "errors": routing_result.get("errors", []) + comms_result.get("errors", []),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run_commander(
    event: dict | None = None,
    session_id: str = "",
    sim_time: str | None = None,
    allow_ai: bool = True,
) -> dict:
    """
    總指揮主流程。

    sim_time：本次執行要套用的模擬時間（不影響全域時鐘）。
              也可放在 event["sim_time"]。留空則使用當下模擬時間。
    """
    started = time.monotonic()
    requested_time = sim_time or (event or {}).get("sim_time")

    with sim_clock.override(requested_time):
        incidents = _load_incidents(event)
        if not incidents:
            return {
                "status": "no_incidents",
                "message": "無事件需要處理",
                "sim_time": sim_clock.now_str(),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "advisories": [],
            }

        # A worker thread starts with an empty context, so each task re-applies the
        # simulated-time override. Without this the workers would resolve against
        # the global clock instead of this run's requested time.
        effective_time = sim_clock.now_str()
        trigger_cache: dict[str, dict] = {}
        cache_lock = threading.Lock()

        def cached_triggers(timestamp: str) -> dict:
            with cache_lock:
                cached = trigger_cache.get(timestamp)
            if cached is not None:
                return cached
            value = evaluate_data_triggers(timestamp)
            with cache_lock:
                return trigger_cache.setdefault(timestamp, value)

        def process_one(incident: object) -> dict:
            if not incident or not isinstance(incident, dict):
                return {"event_id": "UNKNOWN", "error": "Invalid incident", "status": "failed"}
            try:
                with sim_clock.override(effective_time):
                    return _process_incident(incident, cached_triggers, allow_ai=allow_ai)
            except Exception as e:
                import traceback

                return {
                    "event_id": incident.get("event_id", "?"),
                    "error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc(),
                    "status": "failed",
                }

        # Events are independent, so they run concurrently while the rate limiter
        # keeps Bedrock calls spaced. Results are collected back in payload order.
        if len(incidents) == 1:
            advisories = [process_one(incidents[0])]
        else:
            workers = max(1, min(len(incidents), INCIDENT_MAX_WORKERS))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                advisories = list(pool.map(process_one, incidents))

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "status": "completed",
            "generated_at": sim_clock.now_str(),
            "real_generated_at": datetime.now().strftime(sim_clock.TIME_FMT),
            "sim_time": sim_clock.now_str(),
            "clock": sim_clock.state(),
            "total_incidents": len(incidents),
            "processed": len([a for a in advisories if "error" not in a]),
            "failed": len([a for a in advisories if "error" in a]),
            # 端到端耗時：命題要求 60 秒內完成，這個欄位就是現場可驗證的證據
            "elapsed_ms": elapsed_ms,
            "elapsed_seconds": round(elapsed_ms / 1000, 2),
            "budget_seconds": 60,
            "within_budget": elapsed_ms <= 60_000,
            "advisories": advisories,
        }


# ---------------------------------------------------------------------------
# 儀表板預警摘要（模組 1：門檻判定由程式，摘要由 LLM）
# ---------------------------------------------------------------------------

_ALERT_SUMMARY_CACHE: dict[str, dict] = {}
_ALERT_CACHE_LOCK = threading.Lock()
_ALERT_CACHE_MAX = 32


def generate_alert_summary(
    status: dict,
    data_triggers: dict | None = None,
    sim_time: str | None = None,
) -> dict:
    """
    產出儀表板自動彈窗的分析摘要。

    命題規定「摘要由 LLM 生成，門檻判定由程式運算」，所以這裡收到的是已經算好的
    分級與 SOP 觸發結果，LLM 只負責把它寫成一段指揮官口吻的摘要。
    結果依「時間 + 異常特徵」快取，時間沒推進就不會重複呼叫 Bedrock。
    """
    segments = status.get("segments") or []
    level_a = [s for s in segments if s.get("level") == "A"]
    level_b = [s for s in segments if s.get("level") == "B"]
    triggers = data_triggers or {}
    triggered_numbers = list(triggers.get("triggered_numbers") or [])

    sim = sim_time or status.get("sim_time") or status.get("timestamp") or ""
    signature = "|".join([
        sim,
        ",".join(sorted(s["segment_id"] for s in level_a)),
        ",".join(sorted(s["segment_id"] for s in level_b)),
        ",".join(str(n) for n in sorted(triggered_numbers)),
    ])

    with _ALERT_CACHE_LOCK:
        hit = _ALERT_SUMMARY_CACHE.get(signature)
        if hit is not None:
            return hit

    if not level_a and not level_b and not triggered_numbers:
        payload = {
            "sim_time": sim,
            "has_alert": False,
            "summary": "路網運作正常，未達 SOP 預警門檻，無須啟動應變。",
            "source": "deterministic",
            "level_a": [],
            "level_b": [],
            "triggered_sop_numbers": [],
            "sop_clauses": [],
        }
        _remember_alert(signature, payload)
        return payload

    def describe(items: list[dict]) -> str:
        return "、".join(
            f"{s['road_name']} {round(float(s['saturation_score']) * 100)}%"
            f"（時速 {s['avg_speed']} 公里）"
            for s in items
        ) or "無"

    trigger_lines = []
    for check in triggers.get("checks") or []:
        if check.get("triggered"):
            trigger_lines.append(
                f"SOP 第 {check['sop_number']} 條 {check['sop_title']}：{check['reason']}"
            )

    trigger_segments = [
        s for s in segments
        if sop_rules.is_trigger_segment(s["segment_id"]) and s.get("level") in {"A", "B"}
    ]

    facts = [
        f"現在時間：{sim}",
        f"A 級癱瘓路段（飽和度 ≥ 95%）：{describe(level_a)}",
        f"B 級壅擠路段（飽和度 ≥ 85%）：{describe(level_b)}",
        "城市應變觸發路段狀態："
        + (
            "、".join(
                f"{s['road_name']} {round(float(s['saturation_score']) * 100)}%"
                for s in trigger_segments
            )
            or "忠孝東路四段與光復南路均未達級別"
        ),
    ]
    facts.extend(trigger_lines)

    clause_numbers = [1, *triggered_numbers]
    if level_a:
        clause_numbers.append(2)
    sop_clauses = policy.clauses_payload(clause_numbers)

    prompt = f"""你是台北市交控中心的 AI 值班指揮官。以下是系統剛偵測到的路網異常與 SOP 觸發結果，請寫一段主動預警摘要給指揮官。

【程式判定結果】
{chr(10).join('- ' + line for line in facts)}

【SOP 條文原文】
{chr(10).join(c['text'] for c in sop_clauses)[:2500]}

【輸出要求】
- 150 字以內的單一段落，不分段、不使用清單或 Markdown
- 先講最嚴重的狀況，再講應立即啟動的處置，並標明 SOP 條號
- 只能引用上列數值，不得自行新增任何數字
- 提醒哪些路段是城市應變觸發路段（僅忠孝東路四段與光復南路達級別才啟動長綠燈時制）
"""

    try:
        result = _call_bedrock(
            prompt,
            "你是台北市交控中心值班指揮官，語氣簡潔果斷。只依提供的數值作答，禁止新增數字。",
            "alert-summary",
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("fallback_reason", "unavailable"))
        summary = _sanitize_ai_text(result.get("response", ""))
        if not summary:
            raise RuntimeError("empty summary")
        source = "ai_generated"
    except Exception as exc:
        logger.warning(f"預警摘要 AI 生成失敗，改用確定性摘要: {exc}")
        parts = []
        if level_a:
            parts.append(f"{len(level_a)} 路段達 A 級癱瘓（{describe(level_a)}）")
        if level_b:
            parts.append(f"{len(level_b)} 路段達 B 級壅擠（{describe(level_b)}）")
        if trigger_lines:
            parts.append("；".join(trigger_lines))
        summary = "；".join(parts) + "。請依 SOP 啟動相應應變。"
        source = "fallback"

    payload = {
        "sim_time": sim,
        "has_alert": True,
        "summary": summary,
        "source": source,
        "level_a": [
            {
                "segment_id": s["segment_id"],
                "road_name": s["road_name"],
                "saturation_score": s["saturation_score"],
                "avg_speed": s["avg_speed"],
                "is_trigger_segment": sop_rules.is_trigger_segment(s["segment_id"]),
            }
            for s in level_a
        ],
        "level_b": [
            {
                "segment_id": s["segment_id"],
                "road_name": s["road_name"],
                "saturation_score": s["saturation_score"],
                "avg_speed": s["avg_speed"],
                "is_trigger_segment": sop_rules.is_trigger_segment(s["segment_id"]),
            }
            for s in level_b
        ],
        "triggered_sop_numbers": triggered_numbers,
        "sop_triggers": [
            {
                "sop_number": c["sop_number"],
                "sop_title": c["sop_title"],
                "reason": c["reason"],
                "actions": c.get("actions", []),
            }
            for c in (triggers.get("checks") or [])
            if c.get("triggered")
        ],
        "sop_clauses": sop_clauses,
    }
    _remember_alert(signature, payload)
    return payload


def _remember_alert(signature: str, payload: dict) -> None:
    with _ALERT_CACHE_LOCK:
        if len(_ALERT_SUMMARY_CACHE) >= _ALERT_CACHE_MAX:
            _ALERT_SUMMARY_CACHE.clear()
        _ALERT_SUMMARY_CACHE[signature] = payload


# ---------------------------------------------------------------------------
# What-if 對話顧問
# ---------------------------------------------------------------------------

_chat_sessions: dict[str, list] = {}
_chat_lock = threading.Lock()
_CHAT_SESSION_MAX = 64


def _history(session_id: str) -> list:
    if not session_id:
        return []
    with _chat_lock:
        return list(_chat_sessions.get(session_id) or [])


def _remember_history(session_id: str, messages: list) -> None:
    if not session_id or not messages:
        return
    # 一輪對話含使用者訊息、工具往返與回覆，保留最後 N 輪的訊息即可
    trimmed = messages[-(CHAT_HISTORY_TURNS * 6):]
    with _chat_lock:
        if session_id not in _chat_sessions and len(_chat_sessions) >= _CHAT_SESSION_MAX:
            _chat_sessions.clear()
        _chat_sessions[session_id] = trimmed


def reset_chat_session(session_id: str) -> None:
    with _chat_lock:
        _chat_sessions.pop(session_id, None)


_CLAUSE_MENTION = re.compile(r"第\s*([1-7])\s*條")


def run_what_if(prompt: str, session_id: str = "", sim_time: str | None = None) -> dict:
    """
    透過 Amazon Bedrock 執行 What-if 情境問答。

    與先前版本的差異：
      - context 補上人流／漫遊與路網幾何，不再只有車流
      - 顧問可呼叫 traffic_math / policy 工具，答案與建議書同源
      - 依 session_id 保留對話歷史，追問不會斷線
      - 回覆附上實際引用到的 SOP 條文原文
    """
    from backend.agents.advisor_tools import build_tools

    with sim_clock.override(sim_time):
        current_time = sim_clock.now_str()

    triggers = evaluate_data_triggers(current_time)
    traffic_context = traffic_math.get_current_traffic_context(current_time)
    crowd_context = traffic_math.get_current_crowd_context(current_time)
    sop_text = policy.read_traffic_sop().get("sop_text", "")[:4000]

    system_prompt = f"""你是「城市應變指揮官」，台北市交控中心的 AI 決策顧問。

【身分與口吻】
以交控中心資深長官的專業口吻回答。語氣簡潔、果斷、有權威感。

【工具使用】
你可以呼叫工具取得確定性計算結果，遇到下列問題務必先呼叫工具再回答，不要自行推算：
- 替代路徑、主疏散、為何排除某條路 → evacuation_route
- 預計恢復時間 ETE → recovery_time
- 號誌配時或警力需求 → signal_plan
- 條文原文或條號確認 → lookup_sop_clause
- 單一基地台人數、增幅、歷史峰值 → station_detail
- 目前哪些 SOP 條款已觸發 → sop_trigger_status
- 路段相交關係、容量、分流建議 → network_geometry

【嚴格禁止事項】
- 禁止輸出任何 LaTeX 數學符號（如 $...$、\\frac 等）
- 禁止輸出程式碼變數名稱（如 Saturation_Score、capacity_vph）
- 禁止使用 Markdown 程式碼區塊、標題、粗體、表格或分隔線
- 所有數值直接用中文表述（例：「飽和度 95%」而非「Saturation_Score = 0.95」）

【回覆格式要求】
- 硬性上限 {NARRATIVE_CHAR_LIMIT} 個中文字；只輸出「判斷：」「建議：」「行動指令：」三個純文字短段落
- 每段最多三句，優先保留可執行指令，禁止重述全部路段明細
- 時間格式一律 YYYY-MM-DD HH:MM
- 引用 SOP 時標示條號（例：依據 SOP 第 2 條）

【資料紀律】
- 只能引用下方 SOP、路網狀態、人流狀態或工具回傳結果，禁止猜測或虛構任何數字、日期與路段
- 所稱目前時間只能使用「現在時間」
- 未經資料明示，不得自行提出固定回報間隔、號誌調整比例或人力數量
- 只有忠孝東路四段 (RD_TPE_001) 與光復南路 (RD_TPE_002) 是 SOP 第 1 條的城市應變觸發路段，
  其他路段達 A 級只作紅燈顯示，不啟動長綠燈時制與替代路徑引導

【知識基礎】
交通應變標準程序：
{sop_text}

現在時間：{current_time}
（以下狀態即為此刻的即時數據；你不知道此時間之後會發生什麼事，
  回答時一律以「現在時間」為基準，不得推測或引用未來時間的數據。）

當前路網車流狀態：
{json.dumps(traffic_context, ensure_ascii=False)}

當前基地台人流與漫遊狀態：
{json.dumps(crowd_context, ensure_ascii=False)}

目前已由程式判定觸發的 SOP 條款：{triggers['triggered_numbers']}（多語通報：{triggers['multilingual_required']}）
"""

    result = _call_bedrock(
        prompt,
        system_prompt,
        session_id,
        tools=build_tools(current_time),
        messages=_history(session_id),
    )

    if not result.get("ok"):
        # The consultant is advisory only, so an unavailable model degrades to a
        # clear notice instead of surfacing the vendor error to the dashboard.
        result["response"] = (
            "AI 策略顧問目前無法連線，請稍後重試。"
            "即時路網狀態、事件處置建議書與多語通報均不受影響，仍可正常使用。"
        )
        result["sim_time"] = current_time
        result["cited_clauses"] = []
        result["tools_used"] = []
        return result

    response = _sanitize_ai_text(result.get("response", ""))
    response = re.sub(r"每\s*(?:\d+|[一二三四五六七八九十]+)\s*分鐘", "持續", response)
    result["response"] = _limit_narrative(response)
    result["sim_time"] = current_time
    result["data_as_of"] = traffic_context.get("資料時間")
    result["cited_clauses"] = policy.clauses_payload(
        {int(n) for n in _CLAUSE_MENTION.findall(response)}
    )

    if session_id and result.get("messages"):
        _remember_history(session_id, result["messages"])
    result.pop("messages", None)
    return result


# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------


DEFAULT_BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"


def bedrock_settings() -> dict:
    return {
        "model_id": os.environ.get("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID),
        "region": os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-west-2")),
        "max_tokens": BEDROCK_MAX_TOKENS,
        "temperature": BEDROCK_TEMPERATURE,
        "min_call_interval": BEDROCK_MIN_CALL_INTERVAL,
    }


def probe_bedrock() -> dict:
    """
    輕量連線探測，供 /api/health?probe=true 使用。

    模型 ID 或 IAM 權限只要有一點不對，所有 LLM 功能都會靜默退回確定性 fallback，
    畫面看起來正常但其實沒接上 AI。這是唯一會把供應商錯誤訊息回傳的路徑
    （運維用途，不經過建議書或對話回覆），Demo 前務必先打一次確認。
    """
    settings = bedrock_settings()
    started = time.monotonic()
    result = _call_bedrock(
        "回覆「就緒」兩個字。",
        "你是連線測試回應器，只回覆兩個字。",
        "healthcheck",
        expose_error=True,
    )
    return {
        "ok": bool(result.get("ok")),
        "model_id": settings["model_id"],
        "region": settings["region"],
        "latency_ms": int((time.monotonic() - started) * 1000),
        "reason": result.get("fallback_reason", ""),
        "error": result.get("error", ""),
        "sample": (result.get("response") or "")[:40],
        "hint": (
            ""
            if result.get("ok")
            else "確認 BEDROCK_MODEL_ID 是否為該區域有效的 inference profile / model ID，"
                 "以及 Task Role 是否具備該模型的 bedrock:InvokeModel 權限"
        ),
    }


def _call_bedrock(
    prompt: str,
    system_prompt: str,
    session_id: str,
    tools: list | None = None,
    messages: list | None = None,
    expose_error: bool = False,
) -> dict:
    """透過 Amazon Bedrock (Strands SDK) 回應。"""

    settings = bedrock_settings()

    try:
        from strands import Agent
        from strands.models.bedrock import BedrockModel

        # Respect the model's request rate before opening a new call.
        _bedrock_rate_limiter.acquire()

        # Latency scales with generated tokens, and the 60-second demo budget is
        # the binding constraint. Low temperature also keeps repeated Demo runs
        # close to reproducible.
        model = BedrockModel(
            model_id=settings["model_id"],
            region_name=settings["region"],
            max_tokens=settings["max_tokens"],
            temperature=settings["temperature"],
        )
        agent_kwargs: dict = {
            "model": model,
            "system_prompt": system_prompt,
            # 關掉預設 callback handler：它會把串流內容直接印到 stdout，
            # 多個事件併發時三份回覆會在終端機互相蓋字，日誌也難讀。
            "callback_handler": None,
        }
        if tools:
            agent_kwargs["tools"] = tools
        if messages:
            agent_kwargs["messages"] = list(messages)

        agent = Agent(**agent_kwargs)
        result = agent(prompt)

        return {
            "session_id": session_id,
            "prompt": prompt,
            "response": str(result),
            "model": f"bedrock/{settings['model_id']}",
            "messages": list(getattr(agent, "messages", []) or []),
            "tools_used": _tool_names_from(getattr(agent, "messages", []) or []),
            "ok": True,
            "timestamp": datetime.now().strftime(sim_clock.TIME_FMT),
        }
    except ImportError as e:
        logger.error("Strands SDK 未安裝，無法呼叫 Bedrock")
        return _bedrock_failure(session_id, prompt, "sdk_missing", e if expose_error else None)
    except Exception as e:
        # The vendor message is logged for operators. It is only returned when the
        # caller is the operator-facing health probe, so it cannot reach an
        # advisory, a chat reply or the dashboard.
        logger.error(f"Bedrock 呼叫失敗: {type(e).__name__}: {e}")
        return _bedrock_failure(session_id, prompt, "service_error", e if expose_error else None)


def _tool_names_from(messages: list) -> list[str]:
    """從對話訊息裡挑出實際被呼叫的工具名稱，供 UI 顯示推理依據。"""
    names: list[str] = []
    for message in messages:
        for block in (message or {}).get("content") or []:
            if isinstance(block, dict) and "toolUse" in block:
                name = (block["toolUse"] or {}).get("name")
                if name and name not in names:
                    names.append(name)
    return names


def _bedrock_failure(
    session_id: str,
    prompt: str,
    reason: str,
    exception: BaseException | None = None,
) -> dict:
    """Return a redacted failure result so callers fall back deterministically."""

    payload = {
        "session_id": session_id,
        "prompt": prompt,
        "response": "",
        "ok": False,
        "fallback_reason": reason,
        "tools_used": [],
        "timestamp": datetime.now().strftime(sim_clock.TIME_FMT),
    }
    if exception is not None:
        payload["error"] = f"{type(exception).__name__}: {exception}"
    return payload
