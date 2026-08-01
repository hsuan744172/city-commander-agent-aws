"""
Architect Commander Agent — 總指揮 (FastAPI 同 process 版)。
協調 Policy / Router / Comms，彙整交控中心建議書。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from backend import sim_clock
from backend.agents.comms import run_comms
from backend.agents.policy import run_assessment
from backend.agents.router import run_routing
from backend.data_source import get_data_path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LIVE_INCIDENTS_FILE = DATA_DIR / "live_incidents.json"


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


def _load_crowd_data(bs_id: str, timestamp: str | None = None) -> dict | None:
    """截至查詢時間、該基地台的最新一筆人流資料。"""
    from backend.agents.traffic_math import _get_time_slice, _load_crowd_density

    df = _load_crowd_density()
    bs_df = df[df["BS_ID"] == bs_id]
    if bs_df.empty:
        return None

    row, _ = _get_time_slice(bs_df, timestamp, key_col="BS_ID")
    if row.empty:
        return None

    r = row.iloc[0]
    growth_val = r["Growth_Rate"]
    if isinstance(growth_val, str):
        growth_val = float(growth_val.replace("%", "").strip())
    else:
        growth_val = float(growth_val)
    return {
        "bs_id": bs_id,
        "user_count": int(r["User_Count"]),
        "growth_rate": growth_val,
        "roaming_user_pct": float(r["Roaming_User_Pct"]),
        "data_as_of": pd.Timestamp(r["Timestamp"]).strftime(sim_clock.TIME_FMT),
    }


def _get_nearby_stations(segment_id: str) -> list[str]:
    road_network_file = get_data_path("road_network_geometry.json")
    if not road_network_file.exists():
        return []
    with open(road_network_file, encoding="utf-8") as f:
        network = json.load(f)
    for seg in network:
        if seg["segment_id"] == segment_id:
            return seg.get("nearby_stations", [])
    return []


def _get_affected_ids(incident: dict, traffic_data: dict) -> list[str]:
    primary = incident.get("affected_segment") or ""
    affected = [primary] if primary.startswith("RD_") else []
    for seg_id, info in traffic_data.items():
        if seg_id != primary and info.get("saturation_score", 0) >= 0.85:
            affected.append(seg_id)
    return affected


def _process_incident(incident: dict) -> dict:
    if not incident or not isinstance(incident, dict):
        return {"event_id": "UNKNOWN", "error": "Invalid incident", "status": "failed"}

    event_id = incident.get("event_id") or "UNKNOWN"
    # 事件未帶時間 → 視為「當下」發生，交由模擬時鐘決定
    timestamp = sim_clock.resolve(incident.get("timestamp")).strftime(sim_clock.TIME_FMT)
    affected_segment = incident.get("affected_segment") or ""
    event_type = incident.get("type") or ""

    # --- 判定事件分類 ---
    is_road_incident = affected_segment.startswith("RD_") and event_type != "Power_Failure"
    is_crowd_incident = affected_segment.startswith("BS_")
    is_signal_failure = event_type == "Power_Failure" or "號誌故障" in (incident.get("description") or "") or "號誌失效" in (incident.get("description") or "")

    # Phase 1: Policy
    traffic_data = _load_traffic_data(timestamp)
    crowd_data = _load_crowd_data(affected_segment, timestamp) if is_crowd_incident else None

    policy_result = run_assessment({"incident": incident, "traffic_data": traffic_data, "crowd_data": crowd_data, "timestamp": timestamp})
    policy_result = policy_result if isinstance(policy_result, dict) else {}

    # Phase 2: 依事件類型分流處理
    routing_result = {}
    special_advisory = {}

    if is_road_incident and policy_result.get("requires_traffic_routing"):
        # SOP 第 2 條：車禍路障 → 路徑 + ETE
        affected_ids = _get_affected_ids(incident, traffic_data)
        routing_result = run_routing({"incident": incident, "affected_segment_ids": affected_ids, "timestamp": timestamp})
        routing_result = routing_result if isinstance(routing_result, dict) else {}

    elif is_crowd_incident:
        # SOP 第 3 條：捷運人流 → 由 AI 根據 SOP + 數據產出處置方案
        special_advisory = _generate_special_advisory(
            sop_type="crowd",
            incident=incident,
            context={
                "affected_station": affected_segment,
                "crowd_data": crowd_data,
                "policy_summary": policy_result.get("summary", ""),
            },
        )
        # 仍計算 ETE (SOP 第 7 條適用所有事件)
        from backend.agents.traffic_math import calculate_ete
        ete_data = calculate_ete(incident.get("severity") or "High", [affected_segment], timestamp)
        if ete_data and isinstance(ete_data, dict) and "ete_minutes" in ete_data:
            routing_result = {"ete_result": {
                "ete_minutes": ete_data["ete_minutes"],
                "severity": ete_data.get("severity", ""),
                "base_clearance_minutes": ete_data.get("base_clearance_minutes", 0),
                "congestion_penalty_minutes": ete_data.get("congestion_penalty_minutes", 0),
                "avg_saturation_score": ete_data.get("avg_saturation_score", 0),
                "calculation_source": "SOP 第 7 條公式",
            }, "errors": []}

    elif is_signal_failure:
        # SOP 第 5 條：號誌故障 → 由 AI 根據 SOP + 路網數據產出處置方案
        intersections = []
        road_network_file = get_data_path("road_network_geometry.json")
        if road_network_file.exists():
            with open(road_network_file, encoding="utf-8") as f:
                network = json.load(f)
            for seg in network:
                if seg["segment_id"] == affected_segment:
                    intersections = seg.get("intersections", [])
                    break

        special_advisory = _generate_special_advisory(
            sop_type="signal",
            incident=incident,
            context={
                "affected_segment": affected_segment,
                "intersections": intersections,
                "police_required": len(intersections) * 2,
            },
        )
        # 仍計算 ETE (SOP 第 7 條適用所有事件)
        from backend.agents.traffic_math import calculate_ete
        ete_data = calculate_ete(incident.get("severity") or "Medium", [affected_segment], timestamp)
        if ete_data and isinstance(ete_data, dict) and "ete_minutes" in ete_data:
            routing_result = {"ete_result": {
                "ete_minutes": ete_data["ete_minutes"],
                "severity": ete_data.get("severity", ""),
                "base_clearance_minutes": ete_data.get("base_clearance_minutes", 0),
                "congestion_penalty_minutes": ete_data.get("congestion_penalty_minutes", 0),
                "avg_saturation_score": ete_data.get("avg_saturation_score", 0),
                "calculation_source": "SOP 第 7 條公式",
            }, "errors": []}

    # Phase 3: Comms
    nearby = _get_nearby_stations(affected_segment)
    if is_crowd_incident and affected_segment not in nearby:
        nearby.append(affected_segment)

    comms_result = run_comms({"incident": incident, "routing_result": routing_result, "nearby_stations": nearby, "timestamp": timestamp})
    comms_result = comms_result if isinstance(comms_result, dict) else {}

    # Assemble advisory
    advisory = _assemble_advisory(incident, policy_result, routing_result, comms_result, timestamp)

    # 附加特殊處置方案
    if special_advisory:
        advisory["special_advisory"] = special_advisory

    # --- Phase 4: AI 整合建議書 ---
    advisory["ai_narrative"] = _generate_ai_narrative(incident, policy_result, routing_result, comms_result, special_advisory)

    return advisory


def _generate_special_advisory(sop_type: str, incident: dict, context: dict) -> dict:
    """
    透過 Amazon Bedrock Claude 根據 SOP 原文與即時數據，動態產出 SOP 3/5 的特殊處置方案。
    若 Bedrock 不可用則 fallback 到基本結構。
    """

    from backend.agents.policy import read_traffic_sop

    sop_data = read_traffic_sop()
    sop_text = sop_data.get("sop_text", "")[:3000]

    if sop_type == "crowd":
        station = context.get("affected_station", "")
        crowd_info = context.get("crowd_data") or {}
        user_count = crowd_info.get("user_count", "未知")
        growth_rate = crowd_info.get("growth_rate", "未知")

        prompt = f"""根據以下 SOP 原文與即時數據，產出「捷運與接駁分流處置方案」。

【SOP 原文】
{sop_text}

【即時數據】
- 受影響站點: {station}
- 事件描述: {incident.get('description', '')}
- 站點人數: {user_count}
- 人流增幅: {growth_rate}

【輸出要求】
以條列式列出 4-6 項具體處置行動，包含：
1. 對北捷的建議（如過站不停、加開班次等）
2. 對公車處的請求（接駁調度）
3. 對人群的引導方向（明確指出分流目標站）
4. 對警力的協調需求
每項行動 15-25 字，不要使用任何程式碼符號。"""

        title = "捷運與接駁分流處置方案"
        fallback_actions = [
            f"建議北捷針對 {station} 啟動應變措施",
            "通知公車處調度接駁專車",
            "引導群眾至鄰近站點分流",
            "協調警力維持站體秩序",
        ]

    else:  # signal
        segment = context.get("affected_segment", "")
        intersections = context.get("intersections", [])
        police = context.get("police_required", 0)

        prompt = f"""根據以下 SOP 原文與路網數據，產出「號誌故障人工指揮派遣方案」。

【SOP 原文】
{sop_text}

【路網數據】
- 受影響路段: {incident.get('location', segment)}
- 受影響路口: {'、'.join(intersections) if intersections else '待確認'}
- 路口數: {len(intersections)}
- 建議警力: {police} 人（每路口 2 人）

【輸出要求】
以條列式列出 4-6 項具體處置行動，包含：
1. 受影響範圍說明
2. 警力派遣數量與部署位置
3. 對用路人的即時指引
4. 修復估計或後續追蹤
每項行動 15-25 字，不要使用任何程式碼符號。"""

        title = "號誌故障人工指揮派遣方案"
        fallback_actions = [
            f"受影響路段：{incident.get('location', segment)}",
            f"需派遣警力：{police} 人（每路口 2 人）",
            f"受影響路口：{'、'.join(intersections) if intersections else '待確認'}",
            "啟動人工交通指揮至號誌修復",
        ]

    # 透過 Bedrock Claude 產出處置方案
    try:
        result = _call_bedrock(prompt, "你是交控中心 AI 顧問，請產出處置方案。", "special")
        ai_response = result.get("response", "")
        if ai_response and "錯誤" not in ai_response and "API" not in ai_response:
            # 解析 AI 回應為條列式
            actions = [line.strip().lstrip("0123456789.、-•·） ") for line in ai_response.split("\n") if line.strip() and len(line.strip()) > 5]
            if actions:
                return {"type": sop_type, "title": title, "actions": actions[:8], "source": "ai_generated", **context}
    except Exception as e:
        logger.warning(f"特殊處置 AI 生成失敗，使用 fallback: {e}")

    # Fallback
    return {"type": sop_type, "title": title, "actions": fallback_actions, "source": "fallback", **context}


def _generate_ai_narrative(incident: dict, policy_result: dict, routing_result: dict, comms_result: dict, special_advisory: dict) -> str:
    """
    透過 Amazon Bedrock Claude 將計算數據與 SOP 原文整合為專業建議書敘述。
    若 Bedrock 不可用則 fallback 到結構化文字。
    """

    from backend.agents.policy import read_traffic_sop

    # 讀取 SOP 原文
    sop_data = read_traffic_sop()
    sop_text = sop_data.get("sop_text", "")[:4000]

    # 組裝計算數據摘要
    incident_summary = (
        f"事件 {incident.get('event_id')}: {incident.get('description', '')}\n"
        f"位置: {incident.get('location', '')}, 路段: {incident.get('affected_segment', '')}\n"
        f"狀態: {incident.get('status', '')}, 嚴重度: {incident.get('severity', '')}\n"
        f"時間: {incident.get('timestamp', '')}"
    )

    policy_summary = f"交通分級: {policy_result.get('max_level', 'Normal')}\n摘要: {policy_result.get('summary', '')}"

    route_summary = ""
    route_rec = (routing_result or {}).get("route_recommendation")
    ete = (routing_result or {}).get("ete_result")
    if route_rec:
        route_summary = (
            f"主疏散路徑: {route_rec.get('primary_route_name', '')} "
            f"(容量 {route_rec.get('capacity_vph', 0)} 車/時, 飽和度 {route_rec.get('current_saturation', 0)*100:.0f}%)\n"
            f"選擇依據: {route_rec.get('selection_reason', '')}\n"
            f"次要路線: {', '.join(r.get('name','') for r in route_rec.get('secondary_routes', []))}"
        )
    if ete:
        route_summary += (
            f"\nETE: {ete.get('ete_minutes', 0)} 分鐘 "
            f"(基礎清除 {ete.get('base_clearance_minutes', 0)} + 壅塞懲罰 {ete.get('congestion_penalty_minutes', 0)})"
        )

    special_summary = ""
    if special_advisory:
        special_summary = f"特殊處置: {special_advisory.get('title', '')}\n動作: {'; '.join(special_advisory.get('actions', []))}"

    comms_summary = ""
    msgs = (comms_result or {}).get("messages", [])
    if msgs:
        comms_summary = f"通報語言: {', '.join(m.get('language','') for m in msgs)}"
        if (comms_result or {}).get("trigger_sop6"):
            comms_summary += " (SOP 第 6 條多語觸發)"

    prompt = f"""你是台北市交控中心的 AI 決策顧問。根據以下計算數據與 SOP 原文，撰寫一份正式的「交控中心建議書」。

【計算數據】
{incident_summary}

{policy_summary}

{route_summary}

{special_summary}

{comms_summary}

【交通應變 SOP 原文】
{sop_text}

【輸出格式】
- 全文硬性上限 450 個中文字
- 只准輸出「判斷：」「建議：」「行動指令：」三個純文字短段落
- 每段最多三句，不使用 Markdown 標題、粗體、表格、清單或分隔線
- 時間一律使用 YYYY-MM-DD HH:MM
- 只引用上述計算數據與 SOP，不得自行增加回報間隔、人力、時制比例或其他數字
- 所有數值使用自然中文，例如「飽和度 95%」

【禁止事項】
- 禁止 LaTeX 符號、程式碼變數名、Markdown 程式碼區塊
- 禁止輸出英文資料欄位名稱或路段代碼
- 使用自然中文，以交控長官口吻撰寫
"""

    # 透過 Bedrock Claude 產出建議書
    try:
        system_prompt = (
            "你是台北市交控中心 AI 決策顧問。只可依提供的 SOP 與計算結果作答；"
            "輸出三個純文字短段落，禁止 Markdown 與未提供的數字，全文不得超過 450 字。"
        )
        result = _call_bedrock(prompt, system_prompt, "narrative")
        response = result.get("response", "")
        for forbidden in ("```", "**", "###", "##", "#", "$", "\\frac", "Saturation_Score", "capacity_vph"):
            response = response.replace(forbidden, "")
        response = response.strip()
        if len(response) > 500:
            shortened = response[:500]
            boundary = max(shortened.rfind(mark) for mark in ("。", "！", "？"))
            response = shortened[: boundary + 1] if boundary >= 350 else shortened
        return response
    except Exception as e:
        logger.error(f"AI 建議書生成失敗: {e}")
        description = incident.get("description") or "事件已受理"
        location = incident.get("location") or "受影響區域"
        return (
            f"判斷：{location}{description}，已依交通分級與應變程序完成判定。\n"
            "建議：採用系統核定之疏散路徑與通報內容，並持續監控路網狀態。\n"
            "行動指令：立即執行建議書所列號誌、疏導及跨單位協調措施。"
        )


def _assemble_advisory(incident, policy_result, routing_result, comms_result, timestamp):
    incident = incident if isinstance(incident, dict) else {}
    policy_result = policy_result if isinstance(policy_result, dict) else {}
    routing_result = routing_result if isinstance(routing_result, dict) else {}
    comms_result = comms_result if isinstance(comms_result, dict) else {}

    event_id = incident.get("event_id", "UNKNOWN")
    triggered_sops = [s for s in policy_result.get("triggered_sops", []) if isinstance(s, dict) and s.get("triggered")]
    route_rec = routing_result.get("route_recommendation") or None
    ete = routing_result.get("ete_result") or None

    return {
        "advisory_type": "交控中心建議書",
        # generated_at 走模擬時鐘（建議書的情境時間），real_generated_at 才是實際產出時間
        "generated_at": sim_clock.now_str(),
        "real_generated_at": datetime.now().strftime(sim_clock.TIME_FMT),
        "event_id": event_id,
        "event_timestamp": timestamp,
        "event_identification": {
            "event_id": event_id,
            "type": incident.get("type", ""),
            "location": incident.get("location", ""),
            "affected_segment": incident.get("affected_segment", ""),
            "status": incident.get("status", ""),
            "severity": incident.get("severity", ""),
            "description": incident.get("description", ""),
            "triggered_sop_articles": [{"sop_number": s["sop_number"], "title": s["sop_title"], "reason": s["reason"]} for s in triggered_sops],
        },
        "traffic_classification": {
            "max_level": policy_result.get("max_level", "Normal"),
            "congestion_details": policy_result.get("congestion_levels", []),
        },
        "route_advisory": {
            "primary_evacuation_route": route_rec,
            "ete_estimate": ete,
            "signal_adjustments": routing_result.get("signal_suggestions", []),
        },
        "public_communications": {
            "trigger_multilingual_sop6": comms_result.get("trigger_sop6", False),
            "roaming_checks": comms_result.get("roaming_checks", []),
            "broadcast_messages": comms_result.get("messages", []),
            "cms_broadcast": comms_result.get("cms_broadcast", {}),
        },
        "summary": policy_result.get("summary", ""),
        "errors": routing_result.get("errors", []) + comms_result.get("errors", []),
    }


def run_commander(event: dict | None = None, session_id: str = "", sim_time: str | None = None) -> dict:
    """
    總指揮主流程。

    sim_time：本次執行要套用的模擬時間（不影響全域時鐘）。
              也可放在 event["sim_time"]。留空則使用當下模擬時間。
    """
    requested_time = sim_time or (event or {}).get("sim_time")

    with sim_clock.override(requested_time):
        incidents = _load_incidents(event)
        if not incidents:
            return {
                "status": "no_incidents",
                "message": "無事件需要處理",
                "sim_time": sim_clock.now_str(),
                "advisories": [],
            }

        advisories = []
        for incident in incidents:
            if not incident or not isinstance(incident, dict):
                advisories.append({"event_id": "UNKNOWN", "error": "Invalid incident", "status": "failed"})
                continue
            try:
                advisories.append(_process_incident(incident))
            except Exception as e:
                import traceback
                advisories.append({"event_id": incident.get("event_id", "?"), "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc(), "status": "failed"})

        return {
            "status": "completed",
            "generated_at": sim_clock.now_str(),
            "real_generated_at": datetime.now().strftime(sim_clock.TIME_FMT),
            "sim_time": sim_clock.now_str(),
            "clock": sim_clock.state(),
            "total_incidents": len(incidents),
            "processed": len([a for a in advisories if "error" not in a]),
            "failed": len([a for a in advisories if "error" in a]),
            "advisories": advisories,
        }


def run_what_if(prompt: str, session_id: str = "", sim_time: str | None = None) -> dict:
    """
    透過 Amazon Bedrock 執行 What-if 情境問答。

    sim_time：本次問答要套用的模擬時間（不影響全域時鐘）；
              留空則使用當下模擬時間。LLM 只會看到該時間為止的路網數據。
    """

    # 讀取 SOP 作為 system context
    from backend.agents.policy import read_traffic_sop
    from backend.agents.traffic_math import get_current_traffic_context

    sop_data = read_traffic_sop()
    sop_text = sop_data.get("sop_text", "")[:3000]

    # 數值選擇與格式化一律由 traffic_math 提供；模擬時間限制可見資料範圍。
    with sim_clock.override(sim_time):
        current_time = sim_clock.now_str()
        traffic_context = get_current_traffic_context(current_time)
    traffic_summary = json.dumps(traffic_context, ensure_ascii=False)

    system_prompt = f"""你是「城市應變指揮官」，台北市交控中心的 AI 決策顧問。

【身分與口吻】
以交控中心資深長官的專業口吻回答。語氣簡潔、果斷、有權威感。

【嚴格禁止事項】
- 禁止輸出任何 LaTeX 數學符號（如 $...$、\\frac 等）
- 禁止輸出程式碼變數名稱（如 Saturation_Score、capacity_vph）
- 禁止使用 Markdown 程式碼區塊
- 所有數值直接用中文表述（例：「飽和度 95%」而非「Saturation_Score = 0.95」）

【回覆格式要求】
- 硬性上限 450 個中文字，超過即視為錯誤；只准輸出「判斷：」「建議：」「行動指令：」三個純文字短段落
- 不使用 Markdown 標題、粗體、表格、清單或分隔線
- 每段最多三句，優先保留可執行指令，禁止重述全部路段明細
- 時間格式一律 YYYY-MM-DD HH:MM
- 引用 SOP 時標示條號（例：依據 SOP 第 2 條）

【資料紀律】
- 只能引用下方交通應變程序與路網狀態，禁止補充、猜測或虛構任何數字、日期、路段及監測缺漏
- 所稱目前時間只能使用路網狀態中的「資料時間」
- 未經資料明示，不得自行提出固定回報間隔、號誌調整比例或人力數量
- 路網狀態已包含完整時間切片，必須整體判讀，不得只選第一條路段

【知識基礎】
交通應變標準程序：
{sop_text}

現在時間：{current_time}
（以下路網狀態即為此刻的即時數據；你不知道此時間之後會發生什麼事，
  回答時一律以「現在時間」為基準，不得推測或引用未來時間的數據。）

當前路網狀態：
{traffic_summary}
"""

    result = _call_bedrock(prompt, system_prompt, session_id)
    response = result.get("response", "")
    response = re.sub(r"每\s*(?:\d+|[一二三四五六七八九十]+)\s*分鐘", "持續", response)
    for forbidden in ("```", "\\frac", "Saturation_Score", "capacity_vph", "$"):
        response = response.replace(forbidden, "")
    response = response.strip()
    if len(response) > 500:
        shortened = response[:500]
        boundary = max(shortened.rfind(mark) for mark in ("。", "！", "？"))
        response = shortened[: boundary + 1] if boundary >= 350 else shortened
    result["response"] = response
    result["sim_time"] = current_time
    return result


def _call_bedrock(prompt: str, system_prompt: str, session_id: str) -> dict:
    """透過 Amazon Bedrock (Strands SDK) 回應。"""
    import os

    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    region = os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-west-2"))

    try:
        from strands import Agent
        from strands.models.bedrock import BedrockModel

        model = BedrockModel(model_id=model_id, region_name=region)
        agent = Agent(model=model, system_prompt=system_prompt)
        result = agent(prompt)

        return {
            "session_id": session_id,
            "prompt": prompt,
            "response": str(result),
            "model": f"bedrock/{model_id}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except ImportError:
        return {
            "session_id": session_id,
            "prompt": prompt,
            "response": "Strands SDK 未安裝，請 pip install strands-agents",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        logger.error(f"Bedrock 呼叫失敗: {type(e).__name__}: {e}")
        return {
            "session_id": session_id,
            "prompt": prompt,
            "response": f"Bedrock API 錯誤: {type(e).__name__}: {e}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
