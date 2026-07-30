"""
Comms Agent — 多語通報生成。

職責：
  1. 查詢漫遊率 (透過 traffic_math 模組)
  2. 判定 SOP 第 6 條多語觸發
  3. 依官方範本生成四語通報
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.agents.traffic_math import check_roaming_rate

# 官方範本
TEMPLATE_ACCIDENT = {
    "zh-TW": "「{incident_road}封閉，請改道 {primary_route}，預計延誤 {ete} 分鐘」",
    "en": "「{incident_road} is closed. Please detour via {primary_route}. Estimated delay: {ete} minutes.」",
    "ja": "「{incident_road}は閉鎖中です。{primary_route}へ迂回してください。予想遅延：{ete}分。」",
    "ko": "「{incident_road} 폐쇄됨. {primary_route}(으)로 우회하세요. 예상 지연: {ete}분.」",
}

TEMPLATE_SIGNAL_FAILURE = {
    "zh-TW": "「{road} 號誌故障，請依現場指揮通行」",
    "en": "「Traffic signal failure on {road}. Please follow on-site traffic control.」",
    "ja": "「{road}の信号が故障中です。現場の交通整理に従ってください。」",
    "ko": "「{road} 신호등 고장. 현장 교통 통제에 따라 통행하세요.」",
}


def generate_accident_messages(incident_road: str, primary_route: str, ete_minutes: float, languages: list[str]) -> list[dict]:
    ete_str = str(int(ete_minutes))
    return [
        {"language": lang, "message": TEMPLATE_ACCIDENT[lang].format(incident_road=incident_road, primary_route=primary_route, ete=ete_str), "template_used": "一般事故範本"}
        for lang in languages if lang in TEMPLATE_ACCIDENT
    ]


def generate_signal_failure_messages(road: str, languages: list[str]) -> list[dict]:
    return [
        {"language": lang, "message": TEMPLATE_SIGNAL_FAILURE[lang].format(road=road), "template_used": "號誌故障範本"}
        for lang in languages if lang in TEMPLATE_SIGNAL_FAILURE
    ]


def run_comms(task_payload: dict) -> dict:
    """執行多語通報生成。"""
    task_payload = task_payload if isinstance(task_payload, dict) else {}
    incident = task_payload.get("incident") or {}
    incident = incident if isinstance(incident, dict) else {}
    routing_result = task_payload.get("routing_result") or {}
    routing_result = routing_result if isinstance(routing_result, dict) else {}
    nearby_stations = task_payload.get("nearby_stations") or []
    timestamp = task_payload.get("timestamp") or incident.get("timestamp") or ""

    event_id = incident.get("event_id") or "UNKNOWN"
    event_type = incident.get("type") or ""
    errors: list[str] = []

    # 1. 漫遊率檢查
    roaming_checks = []
    trigger_sop6 = False

    for bs_id in nearby_stations:
        data = check_roaming_rate(bs_id, timestamp)
        if not data or not isinstance(data, dict):
            errors.append(f"漫遊率查詢失敗 ({bs_id}): 回傳 None")
            continue
        if "error" in data:
            errors.append(f"漫遊率查詢失敗 ({bs_id}): {data['error']}")
            continue
        check = {
            "bs_id": bs_id,
            "location_name": data.get("location_name", ""),
            "roaming_pct": data.get("roaming_user_pct", 0),
            "trigger_multilingual": data.get("trigger_sop6_multilingual", False),
        }
        roaming_checks.append(check)
        if check["trigger_multilingual"]:
            trigger_sop6 = True

    # 2. 語言版本
    languages = ["zh-TW", "en", "ja", "ko"] if trigger_sop6 else ["zh-TW"]

    # 3. 生成訊息
    messages = []
    is_signal_failure = (
        event_type == "Power_Failure"
        or "號誌故障" in (incident.get("description") or "")
        or "號誌失效" in (incident.get("description") or "")
    )
    is_crowd_event = (incident.get("affected_segment") or "").startswith("BS_")

    if is_signal_failure:
        # SOP 第 5 條：號誌故障 CMS
        road_name = routing_result.get("incident_name") or incident.get("location") or ""
        messages = generate_signal_failure_messages(road_name, languages)
    elif is_crowd_event:
        # SOP 第 3 條：人流事件不產出車流通報，改為捷運分流提示
        location = incident.get("location") or incident.get("affected_segment") or ""
        messages = [{
            "language": lang,
            "message": f"「{location} 人潮壅擠，建議改至市政府站 (BL18) 搭乘，請配合現場引導」" if lang == "zh-TW"
                else f"「Crowding at {location}. Please use City Hall Station (BL18) instead.」" if lang == "en"
                else f"「{location}付近混雑。市政府駅(BL18)をご利用ください。」" if lang == "ja"
                else f"「{location} 혼잡. 시청역(BL18)을 이용해주세요.」",
            "template_used": "捷運分流範本",
        } for lang in languages]
    else:
        # SOP 第 2 條：車禍路障 CMS
        incident_road = routing_result.get("incident_name") or incident.get("location") or ""
        route_rec = routing_result.get("route_recommendation") or {}
        primary_route = route_rec.get("primary_route_name", "") if isinstance(route_rec, dict) else ""
        ete_data = routing_result.get("ete_result") or {}
        ete_minutes = ete_data.get("ete_minutes", 0) if isinstance(ete_data, dict) else 0

        if incident_road and primary_route and ete_minutes:
            messages = generate_accident_messages(incident_road, primary_route, ete_minutes, languages)
        else:
            missing = [k for k, v in {"incident_road": incident_road, "primary_route": primary_route, "ete_minutes": ete_minutes}.items() if not v]
            errors.append(f"訊息生成資料不完整，缺少: {', '.join(missing)}")

    # 4. CMS 廣播
    cms_broadcast = {
        "event_id": event_id,
        "broadcast_timestamp": timestamp,
        "trigger_sop6_multilingual": trigger_sop6,
        "languages_included": languages,
        "messages": [{"language": m["language"], "content": m["message"]} for m in messages],
    }

    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "roaming_checks": roaming_checks,
        "trigger_sop6": trigger_sop6,
        "messages": messages,
        "cms_broadcast": cms_broadcast,
        "errors": errors,
    }
