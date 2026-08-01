"""
Comms Agent — 多語通報生成。

職責：
  1. SOP 第 6 條觸發判定 — 依 traffic_math.scan_roaming 掃描**全部**基地台
  2. 依官方範本產出 CMS 看板文字（SOP 明訂句式，逐字不改）
  3. 產出民眾簡訊（事故位置／改道指引／預計延誤／求援或避開提醒 四項要點）

CMS 句式由範本保證與 SOP 第 2 條 (b)、第 5 條逐字一致；民眾簡訊為擴充版本，
兩者都在同一回應中產出（SOP 第 6 條：「並於同一回應產出」）。
"""

from __future__ import annotations

from backend.agents import sop_rules, traffic_math

EMERGENCY_CONTACT = "1999"
POLICE_CONTACT = "110"
AMBULANCE_CONTACT = "119"

# --- SOP 第 2 條 (b) 明訂 CMS 句式 -----------------------------------------
TEMPLATE_ACCIDENT = {
    "zh-TW": "{incident_road}封閉，請改道 {primary_route}，預計延誤 {ete} 分鐘",
    "en": "{incident_road} is closed. Please detour via {primary_route}. Estimated delay: {ete} minutes.",
    "ja": "{incident_road}は閉鎖中です。{primary_route}へ迂回してください。予想遅延：{ete}分。",
    "ko": "{incident_road} 폐쇄됨. {primary_route}(으)로 우회하세요. 예상 지연: {ete}분.",
}

# --- SOP 第 5 條明訂 CMS 句式 ---------------------------------------------
TEMPLATE_SIGNAL_FAILURE = {
    "zh-TW": "{road} 號誌故障，請依現場指揮通行",
    "en": "Traffic signal failure on {road}. Please follow on-site traffic control.",
    "ja": "{road}の信号が故障中です。現場の交通整理に従ってください。",
    "ko": "{road} 신호등 고장. 현장 교통 통제에 따라 통행하세요.",
}

# --- SOP 第 3 條人流分流 CMS 句式 -----------------------------------------
TEMPLATE_CROWD = {
    "zh-TW": "{location} 人潮壅擠，請改至{relief}搭乘，並配合現場引導",
    "en": "Crowding at {location}. Please use {relief} instead and follow on-site guidance.",
    "ja": "{location}付近が混雑しています。{relief}をご利用のうえ、係員の誘導に従ってください。",
    "ko": "{location} 혼잡. {relief}을 이용하시고 현장 안내에 따라주세요.",
}

# --- 民眾簡訊：位置 / 改道 / 延誤 / 求援或避開 四項要點 -------------------
SMS_ACCIDENT = {
    "zh-TW": (
        "【交通應變通報】{time}，{location}發生事故，{incident_road}封閉。"
        "請改道 {primary_route} 行駛，預計延誤 {ete} 分鐘。"
        "請避開事故周邊道路，如需協助請撥 {emergency} 或 {police}。"
    ),
    "en": (
        "[Traffic Alert] {time}: An incident at {location} has closed {incident_road}. "
        "Detour via {primary_route}; estimated delay {ete} minutes. "
        "Please avoid the surrounding area. For assistance call {emergency} or {police}."
    ),
    "ja": (
        "【交通情報】{time}、{location}で事故が発生し、{incident_road}は閉鎖中です。"
        "{primary_route}へ迂回してください。予想遅延は{ete}分です。"
        "周辺道路を避け、支援が必要な場合は {emergency} または {police} へご連絡ください。"
    ),
    "ko": (
        "【교통 알림】{time}, {location} 사고로 {incident_road}이(가) 폐쇄되었습니다. "
        "{primary_route}(으)로 우회하시고 예상 지연은 {ete}분입니다. "
        "사고 주변 도로를 피하시고 도움이 필요하면 {emergency} 또는 {police}로 연락하세요."
    ),
}

# 號誌故障簡訊只用路段全名描述位置。事件的 location 欄位本身常已含「號誌故障」
# 字樣（例如「信義威秀/ATT4FUN周邊路燈號誌故障」），代入後會產生重複贅句。
SMS_SIGNAL_FAILURE = {
    "zh-TW": (
        "【號誌故障通報】{time}，{road}號誌故障，改由現場員警人工指揮。"
        "請減速慢行並依指揮通行，預計 {ete} 分鐘內恢復。"
        "請避開該路段路口，遇危險請撥 {police}。"
    ),
    "en": (
        "[Signal Failure] {time}: Signals on {road} have failed and traffic is under manual "
        "police control. Slow down and follow officers' directions. Expected recovery in {ete} "
        "minutes. Please avoid the junctions; call {police} in an emergency."
    ),
    "ja": (
        "【信号故障】{time}、{road}の信号が故障し、警察官による手信号で運用中です。"
        "減速し指示に従ってください。復旧見込みは約{ete}分です。"
        "当該路線の交差点を避け、危険な場合は {police} へご連絡ください。"
    ),
    "ko": (
        "【신호 고장】{time}, {road} 신호등 고장으로 경찰 수신호로 통제됩니다. "
        "감속 후 지시에 따라주세요. 복구 예상 {ete}분. "
        "해당 구간 교차로를 피하시고 위험 시 {police}로 신고하세요."
    ),
}

SMS_CROWD = {
    "zh-TW": (
        "【人流疏導通報】{time}，{location}人潮壅擠，{station_label}將視情況過站不停。"
        "請改至{relief}搭乘或依現場人員引導分流，預計 {ete} 分鐘內紓解。"
        "請避開擁擠出口，如有傷病請撥 {ambulance}。"
    ),
    "en": (
        "[Crowd Advisory] {time}: Heavy crowding at {location}; trains may skip {station_label}. "
        "Please use {relief} or follow on-site guidance. Expected to ease in {ete} minutes. "
        "Avoid congested exits; call {ambulance} for medical help."
    ),
    "ja": (
        "【混雑情報】{time}、{location}が混雑しており、{station_label}は通過運転となる場合があります。"
        "{relief}のご利用または係員の誘導に従ってください。約{ete}分で緩和見込みです。"
        "混雑した出口を避け、負傷の際は {ambulance} へご連絡ください。"
    ),
    "ko": (
        "【혼잡 안내】{time}, {location} 혼잡으로 {station_label} 무정차 통과가 있을 수 있습니다. "
        "{relief}을 이용하거나 현장 안내에 따라주세요. 약 {ete}분 후 완화 예상. "
        "혼잡한 출구를 피하시고 부상 시 {ambulance}로 연락하세요."
    ),
}

_STATION_LABELS = {
    "zh-TW": {
        sop_rules.SOP3_STATION: "捷運國父紀念館站",
        sop_rules.SOP3_RELIEF_STATION: "捷運市政府站 (BL18)",
    },
    "en": {
        sop_rules.SOP3_STATION: "Sun Yat-Sen Memorial Hall Station (BL17)",
        sop_rules.SOP3_RELIEF_STATION: "Taipei City Hall Station (BL18)",
    },
    "ja": {
        sop_rules.SOP3_STATION: "国父紀念館駅 (BL17)",
        sop_rules.SOP3_RELIEF_STATION: "市政府駅 (BL18)",
    },
    "ko": {
        sop_rules.SOP3_STATION: "국부기념관역 (BL17)",
        sop_rules.SOP3_RELIEF_STATION: "시청역 (BL18)",
    },
}


def _station_label(bs_id: str, language: str) -> str:
    return _STATION_LABELS.get(language, {}).get(bs_id, bs_id)


def _format_ete(ete_minutes: object) -> str:
    try:
        return str(int(round(float(ete_minutes))))
    except (TypeError, ValueError):
        return "待評估"


def _render(templates: dict, languages, **fields) -> dict[str, str]:
    return {
        language: templates[language].format(**fields)
        for language in languages
        if language in templates
    }


def run_comms(task_payload: dict) -> dict:
    """
    執行多語通報生成。

    payload：
      incident        事件本體
      classification  sop_rules.classify_incident 的結果
      routing_result  router.run_routing 的結果
      sop6            policy.check_sop6_trigger 的結果（未提供時自行掃描全市）
      nearby_stations 事故周邊基地台（僅作為區域佐證，不決定觸發）
      timestamp       套用的模擬時間
    """
    task_payload = task_payload if isinstance(task_payload, dict) else {}
    incident = task_payload.get("incident") or {}
    incident = incident if isinstance(incident, dict) else {}
    routing_result = task_payload.get("routing_result") or {}
    routing_result = routing_result if isinstance(routing_result, dict) else {}
    nearby_stations = task_payload.get("nearby_stations") or []
    timestamp = task_payload.get("timestamp") or incident.get("timestamp") or ""
    info = task_payload.get("classification") or sop_rules.classify_incident(incident)

    event_id = incident.get("event_id") or "UNKNOWN"
    errors: list[str] = []

    # --- 1. SOP 第 6 條：全市任一基地台 >= 30% 即觸發多語 ---
    sop6 = task_payload.get("sop6")
    if not isinstance(sop6, dict):
        from backend.agents.policy import check_sop6_trigger

        sop6 = check_sop6_trigger(timestamp)

    trigger_sop6 = bool(sop6.get("triggered"))
    languages = list(
        sop6.get("languages")
        or (sop_rules.SOP6_LANGUAGES if trigger_sop6 else sop_rules.SOP6_DEFAULT_LANGUAGES)
    )
    trigger_stations = (sop6.get("evidence") or {}).get("trigger_stations") or []

    # 事故周邊基地台：不決定觸發，但列為「該區域」佐證
    nearby_checks = []
    for bs_id in nearby_stations:
        reading = traffic_math.station_reading(bs_id, timestamp)
        if not reading:
            errors.append(f"周邊基地台查無資料 ({bs_id})")
            continue
        nearby_checks.append({
            "bs_id": bs_id,
            "location_name": reading.get("location_name", ""),
            "roaming_pct": reading.get("roaming_user_pct", 0),
            "roaming_pct_display": reading.get("roaming_user_pct_display", ""),
            "user_count": reading.get("user_count", 0),
            "exceeds_threshold": reading.get("exceeds_sop6_threshold", False),
        })

    # --- 2. 產出 CMS 與民眾簡訊 ---
    ete_minutes = ((routing_result.get("ete_result") or {}).get("ete_minutes"))
    ete_text = _format_ete(ete_minutes)
    location = incident.get("location") or ""
    event_time = incident.get("timestamp") or timestamp
    # CMS 的「<路段>」一律用路網幾何的路段全名，不用事件的 location 描述文字，
    # 否則會產出「信義威秀/ATT4FUN周邊路燈號誌故障 號誌故障」這種重複贅句。
    road_name = (
        routing_result.get("incident_name")
        or traffic_math.segment_name(info.traffic_segment)
        or info.traffic_segment
        or location
    )

    cms_texts: dict[str, str] = {}
    sms_texts: dict[str, str] = {}
    template_used = ""

    if info.is_signal_failure:
        template_used = "SOP 第 5 條號誌故障範本"
        cms_texts = _render(TEMPLATE_SIGNAL_FAILURE, languages, road=road_name)
        sms_texts = _render(
            SMS_SIGNAL_FAILURE,
            languages,
            time=event_time,
            road=road_name,
            ete=ete_text,
            police=POLICE_CONTACT,
        )
    elif info.is_crowd:
        template_used = "SOP 第 3 條捷運分流範本"
        cms_texts = {
            language: TEMPLATE_CROWD[language].format(
                location=location or _station_label(info.station, language),
                relief=_station_label(sop_rules.SOP3_RELIEF_STATION, language),
            )
            for language in languages
            if language in TEMPLATE_CROWD
        }
        sms_texts = {
            language: SMS_CROWD[language].format(
                time=event_time,
                location=location or _station_label(info.station, language),
                station_label=_station_label(info.station, language),
                relief=_station_label(sop_rules.SOP3_RELIEF_STATION, language),
                ete=ete_text,
                ambulance=AMBULANCE_CONTACT,
            )
            for language in languages
            if language in SMS_CROWD
        }
    else:
        template_used = "SOP 第 2 條事故改道範本"
        route_rec = routing_result.get("route_recommendation") or {}
        primary_route = route_rec.get("primary_route_name", "") if isinstance(route_rec, dict) else ""
        if road_name and primary_route and ete_minutes:
            cms_texts = _render(
                TEMPLATE_ACCIDENT,
                languages,
                incident_road=road_name,
                primary_route=primary_route,
                ete=ete_text,
            )
            sms_texts = _render(
                SMS_ACCIDENT,
                languages,
                time=event_time,
                location=location or road_name,
                incident_road=road_name,
                primary_route=primary_route,
                ete=ete_text,
                emergency=EMERGENCY_CONTACT,
                police=POLICE_CONTACT,
            )
        else:
            missing = [
                key
                for key, value in {
                    "事故路段": road_name,
                    "主疏散路段": primary_route,
                    "ETE": ete_minutes,
                }.items()
                if not value
            ]
            errors.append(f"訊息生成資料不完整，缺少: {', '.join(missing)}")

    messages = [
        {
            "language": language,
            # 保留原欄位名（CMS 句式）以維持既有呼叫端
            "message": cms_texts[language],
            "cms_text": cms_texts[language],
            "sms_text": sms_texts.get(language, cms_texts[language]),
            "template_used": template_used,
        }
        for language in languages
        if language in cms_texts
    ]

    cms_broadcast = {
        "event_id": event_id,
        "broadcast_timestamp": timestamp,
        "trigger_sop6_multilingual": trigger_sop6,
        "languages_included": [m["language"] for m in messages],
        "messages": [
            {"language": m["language"], "content": m["cms_text"], "sms": m["sms_text"]}
            for m in messages
        ],
    }

    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "sop6": sop6,
        "trigger_sop6": trigger_sop6,
        "trigger_stations": trigger_stations,
        "roaming_scope": (sop6.get("evidence") or {}).get("scope", "全資料集所有基地台"),
        # 舊欄位名保留，但內容語意已明確為「事故周邊佐證」
        "roaming_checks": nearby_checks,
        "nearby_station_checks": nearby_checks,
        "languages": languages,
        "messages": messages,
        "cms_broadcast": cms_broadcast,
        "message_requirements": {
            "事故位置": True,
            "改道指引": True,
            "預計延誤時間": bool(ete_minutes),
            "求援或避開提醒": True,
        },
        "errors": errors,
    }
