"""
SOP-Policy Agent — 法規驗證與級別判定。

職責：
  1. 判定擁塞級別 (A/B/Normal) — SOP 第 1 條
  2. 判定事件型 SOP 觸發條件 — 第 2、5 條
  3. 判定資料型 SOP 觸發條件 — 第 3、4、6 條（不需要事件，儀表板可主動偵測）
  4. 讀取 SOP 文本並取出被引用的條文原文

規則常數一律取自 sop_rules；數值一律取自 traffic_math。此模組只做判定與組裝。
"""

from __future__ import annotations

import re

from backend.agents import sop_rules, traffic_math
from backend.data_source import get_data_path, get_data_source_name

# 條文標題，供報告顯示與條文原文擷取
SOP_TITLES: dict[int, str] = {
    1: "交通擁塞級別判定",
    2: "車禍與路障應變",
    3: "捷運與接駁分流",
    4: "大巨蛋散場啟動",
    5: "號誌故障應變",
    6: "數位通報與多語化",
    7: "預計恢復時間 (ETE) 計算",
}


def assess_congestion_level(saturation_score: float) -> str:
    """SOP 第 1 條分級。實作在 sop_rules，這裡只做轉呼叫以維持既有介面。"""
    return sop_rules.assess_congestion_level(saturation_score)


# ---------------------------------------------------------------------------
# 事件型觸發 — 第 2、5 條
# ---------------------------------------------------------------------------


def check_sop2_trigger(incident: dict, classification=None) -> dict:
    """SOP 第 2 條：車禍與路障應變。三項條件須同時成立。"""
    info = classification or sop_rules.classify_incident(incident)
    status_ok = info.status in sop_rules.SOP2_STATUSES
    severity_ok = info.severity in sop_rules.SOP2_SEVERITIES
    segment_ok = info.affected_segment.startswith(sop_rules.SOP2_ROAD_PREFIX)
    triggered = status_ok and severity_ok and segment_ok

    if triggered:
        reason = (
            f"事故路段 {info.affected_segment} 狀態為{info.status}、嚴重度{info.severity}，"
            "符合 SOP 第 2 條三項觸發條件"
        )
    else:
        failed = []
        if not status_ok:
            reason_status = info.status or "未提供"
            failed.append(f"狀態={reason_status}（須為 Closed/Blocked/Restricted）")
        if not severity_ok:
            failed.append(f"嚴重度={info.severity or '未提供'}（須為 High/Critical）")
        if not segment_ok:
            failed.append(f"路段={info.affected_segment or '未提供'}（須為 RD_ 車流路段）")
        reason = "未同時滿足三項條件：" + "、".join(failed)

    return {
        "sop_number": 2,
        "sop_title": SOP_TITLES[2],
        "triggered": triggered,
        "reason": reason,
        "evidence": {
            "status": info.status,
            "severity": info.severity,
            "affected_segment": info.affected_segment,
            "status_ok": status_ok,
            "severity_ok": severity_ok,
            "segment_ok": segment_ok,
        },
        "actions": (
            [
                "計算主疏散路徑並避開容量不足或已飽和路段",
                f"主疏散路段啟動長綠燈時制（綠燈配時 +{sop_rules.GREEN_LIGHT_EXTENSION_PCT}%）",
                "產出 CMS 改道文字並標示預計延誤時間",
            ]
            if triggered
            else []
        ),
    }


def check_sop5_trigger(incident: dict, classification=None) -> dict:
    """SOP 第 5 條：號誌故障應變。"""
    info = classification or sop_rules.classify_incident(incident)
    description = (incident or {}).get("description") or ""
    matched_keywords = [k for k in sop_rules.SIGNAL_FAILURE_KEYWORDS if k in description]
    type_match = info.event_type == sop_rules.SIGNAL_FAILURE_TYPE
    triggered = info.is_signal_failure

    if triggered:
        basis = []
        if type_match:
            basis.append(f"事件類型為 {sop_rules.SIGNAL_FAILURE_TYPE}")
        if matched_keywords:
            basis.append(f"描述含「{'、'.join(matched_keywords)}」")
        reason = "、".join(basis) + "，符合 SOP 第 5 條號誌故障特徵"
    else:
        reason = f"事件類型為{info.event_type or '未提供'}，未偵測到號誌故障特徵"

    return {
        "sop_number": 5,
        "sop_title": SOP_TITLES[5],
        "triggered": triggered,
        "reason": reason,
        "evidence": {
            "type": info.event_type,
            "type_match": type_match,
            "matched_keywords": matched_keywords,
        },
        "actions": (
            [
                "產出人工指揮派遣建議（受影響路段、警力人數、估計持續時間）",
                f"每路口派遣 {sop_rules.SOP5_POLICE_PER_INTERSECTION} 名警力",
                "CMS 加註號誌故障，請依現場指揮通行",
            ]
            if triggered
            else []
        ),
    }


# ---------------------------------------------------------------------------
# 資料型觸發 — 第 3、4、6 條。不需要事件，儀表板可主動偵測。
# ---------------------------------------------------------------------------


def check_sop3_trigger(timestamp: str | None = None, reading: dict | None = None) -> dict:
    """
    SOP 第 3 條：捷運與接駁分流。

    觸發條件是純資料條件（BL17 Growth_Rate > 0.30 或 User_Count > 25,000），
    與是否有事件注入無關，因此改為直接讀人流資料判定。原本只在事件提及 BL17
    時才評估，導致儀表板無法主動預警。
    """
    data = reading or traffic_math.station_reading(sop_rules.SOP3_STATION, timestamp)
    if not data:
        return {
            "sop_number": 3,
            "sop_title": SOP_TITLES[3],
            "triggered": False,
            "reason": f"{sop_rules.SOP3_STATION} 在查詢時間無人流資料",
            "evidence": {"station": sop_rules.SOP3_STATION},
            "actions": [],
        }

    growth_rate = float(data.get("growth_rate") or 0)
    user_count = int(data.get("user_count") or 0)
    growth_hit = growth_rate > sop_rules.SOP3_GROWTH_THRESHOLD
    count_hit = user_count > sop_rules.SOP3_USER_COUNT_THRESHOLD
    triggered = growth_hit or count_hit

    hits = []
    if growth_hit:
        hits.append(
            f"人流增幅 {growth_rate:.0%} 超過 {sop_rules.SOP3_GROWTH_THRESHOLD:.0%}"
        )
    if count_hit:
        hits.append(
            f"站內人數 {user_count:,} 人超過 {sop_rules.SOP3_USER_COUNT_THRESHOLD:,} 人"
        )
    reason = (
        f"{data.get('location_name', sop_rules.SOP3_STATION)}：" + "、".join(hits)
        if triggered
        else (
            f"{data.get('location_name', sop_rules.SOP3_STATION)} 人流增幅 {growth_rate:.0%}、"
            f"人數 {user_count:,} 人，均未達分流門檻"
        )
    )

    return {
        "sop_number": 3,
        "sop_title": SOP_TITLES[3],
        "triggered": triggered,
        "reason": reason,
        "evidence": {
            "station": sop_rules.SOP3_STATION,
            "location_name": data.get("location_name", ""),
            "growth_rate": growth_rate,
            "user_count": user_count,
            "growth_threshold": sop_rules.SOP3_GROWTH_THRESHOLD,
            "user_count_threshold": sop_rules.SOP3_USER_COUNT_THRESHOLD,
            "growth_hit": growth_hit,
            "count_hit": count_hit,
            "data_as_of": data.get("data_as_of"),
        },
        "actions": (
            [
                "建議臺北捷運公司於國父紀念館站啟動過站不停",
                "通知公車處調度接駁專車疏運",
                f"引導群眾步行至{_station_label(sop_rules.SOP3_RELIEF_STATION)}分流",
                "協調警力維持站體與出口秩序",
            ]
            if triggered
            else []
        ),
    }


def check_sop4_trigger(timestamp: str | None = None) -> dict:
    """
    SOP 第 4 條：大巨蛋散場啟動。

    觸發：BS_TPE_DOME User_Count 歷史峰值曾達 >= 30,000，且當前 Growth_Rate <= -0.20。
    峰值是跨時間累積狀態，由 traffic_math.station_history 只取 <= 查詢時間的量測計算。
    """
    history = traffic_math.station_history(sop_rules.SOP4_STATION, timestamp)
    if not history or history.get("error") or not history.get("samples"):
        return {
            "sop_number": 4,
            "sop_title": SOP_TITLES[4],
            "triggered": False,
            "reason": f"{sop_rules.SOP4_STATION} 在查詢時間尚無人流資料",
            "evidence": {"station": sop_rules.SOP4_STATION},
            "actions": [],
            "cascades_to": [],
        }

    peak = int(history.get("peak_user_count") or 0)
    growth = float(history.get("current_growth_rate") or 0)
    peak_hit = peak >= sop_rules.SOP4_PEAK_THRESHOLD
    decline_hit = growth <= sop_rules.SOP4_DECLINE_THRESHOLD
    triggered = peak_hit and decline_hit

    if triggered:
        reason = (
            f"{history.get('location_name', '大巨蛋')} 歷史峰值 {peak:,} 人"
            f"（{history.get('peak_at')}）已達 {sop_rules.SOP4_PEAK_THRESHOLD:,} 人，"
            f"且當前人流增幅 {growth:.0%} 低於 {sop_rules.SOP4_DECLINE_THRESHOLD:.0%}，"
            "研判散場已啟動"
        )
    else:
        unmet = []
        if not peak_hit:
            unmet.append(f"歷史峰值 {peak:,} 人未達 {sop_rules.SOP4_PEAK_THRESHOLD:,} 人")
        if not decline_hit:
            unmet.append(
                f"當前人流增幅 {growth:.0%} 未低於 {sop_rules.SOP4_DECLINE_THRESHOLD:.0%}"
            )
        reason = "、".join(unmet)

    return {
        "sop_number": 4,
        "sop_title": SOP_TITLES[4],
        "triggered": triggered,
        "reason": reason,
        "evidence": {
            "station": sop_rules.SOP4_STATION,
            "location_name": history.get("location_name", ""),
            "peak_user_count": peak,
            "peak_at": history.get("peak_at"),
            "current_user_count": history.get("current_user_count"),
            "current_growth_rate": growth,
            "peak_threshold": sop_rules.SOP4_PEAK_THRESHOLD,
            "decline_threshold": sop_rules.SOP4_DECLINE_THRESHOLD,
            "peak_hit": peak_hit,
            "decline_hit": decline_hit,
            "data_as_of": history.get("data_as_of"),
        },
        "actions": (
            [
                "標記大巨蛋散場啟動，進入疏散尖峰應變",
                "提前連動 SOP 第 3 條接駁機制，不待人流門檻觸發",
                "預先於場館周邊部署人流引導與警力",
            ]
            if triggered
            else []
        ),
        # SOP 原文：「並提前連動第 3 條接駁機制」
        "cascades_to": [3] if triggered else [],
    }


def check_sop6_trigger(timestamp: str | None = None, roaming: dict | None = None) -> dict:
    """
    SOP 第 6 條：數位通報與多語化。

    觸發：**任一**基地台 Roaming_User_Pct >= 30%。判定範圍是全資料集，
    不是事故路段周邊基地台。
    """
    scan = roaming or traffic_math.scan_roaming(timestamp)
    triggers = scan.get("trigger_stations") or []
    triggered = bool(scan.get("triggered"))

    if triggered:
        detail = "、".join(
            f"{s['location_name']} {s['roaming_user_pct_display']}" for s in triggers
        )
        reason = (
            f"全市 {scan.get('total_stations', 0)} 個基地台中，"
            f"{detail} 漫遊率已達 {scan.get('threshold_display', '30%')} 門檻"
        )
    else:
        reason = (
            f"全市 {scan.get('total_stations', 0)} 個基地台漫遊率均未達 "
            f"{scan.get('threshold_display', '30%')}，通報僅需繁體中文"
        )

    return {
        "sop_number": 6,
        "sop_title": SOP_TITLES[6],
        "triggered": triggered,
        "reason": reason,
        "evidence": {
            "scope": scan.get("scope", "全資料集所有基地台"),
            "threshold": scan.get("threshold"),
            "total_stations": scan.get("total_stations", 0),
            "trigger_stations": [
                {
                    "bs_id": s["bs_id"],
                    "location_name": s["location_name"],
                    "roaming_user_pct": s["roaming_user_pct"],
                    "roaming_user_pct_display": s["roaming_user_pct_display"],
                }
                for s in triggers
            ],
            "data_as_of": scan.get("data_as_of"),
        },
        "languages": scan.get("languages", list(sop_rules.SOP6_DEFAULT_LANGUAGES)),
        "actions": (
            ["簡訊與 CMS 看板訊息須同時產出多國語言版本"] if triggered else []
        ),
    }


def evaluate_data_triggers(timestamp: str | None = None) -> dict:
    """
    只依資料判定的 SOP 條款（第 3、4、6 條）。

    儀表板用這個做主動預警，事件處置流程也用同一份結果，兩邊不會出現不同答案。
    """
    roaming = traffic_math.scan_roaming(timestamp)
    sop3 = check_sop3_trigger(timestamp)
    sop4 = check_sop4_trigger(timestamp)
    sop6 = check_sop6_trigger(timestamp, roaming=roaming)

    # SOP 第 4 條觸發時「提前連動第 3 條接駁機制」，即使 BL17 人流門檻尚未達到
    if sop4["triggered"] and not sop3["triggered"]:
        sop3 = dict(sop3)
        sop3["cascaded_from"] = 4
        sop3["reason"] = (
            f"{sop3['reason']}；但 SOP 第 4 條已觸發，依原文提前連動第 3 條接駁機制"
        )
        sop3["actions"] = [
            "依 SOP 第 4 條提前連動：預先通知公車處備援接駁專車",
            f"預先規劃群眾往{_station_label(sop_rules.SOP3_RELIEF_STATION)}分流動線",
        ]

    checks = [sop3, sop4, sop6]
    return {
        "query_timestamp": roaming.get("query_timestamp"),
        "data_as_of": roaming.get("data_as_of"),
        "roaming_scan": roaming,
        "sop3": sop3,
        "sop4": sop4,
        "sop6": sop6,
        "checks": checks,
        "triggered_numbers": [c["sop_number"] for c in checks if c["triggered"]],
        "multilingual_required": sop6["triggered"],
        "languages": sop6.get("languages", list(sop_rules.SOP6_DEFAULT_LANGUAGES)),
    }


def _station_label(bs_id: str) -> str:
    labels = {
        "BS_MRT_BL18": "捷運市政府站 (BL18)",
        "BS_MRT_BL17": "捷運國父紀念館站 (BL17)",
        "BS_MRT_BL16": "捷運忠孝敦化站 (BL16)",
    }
    return labels.get(bs_id, bs_id)


SCOPE_EVENT = "event"
SCOPE_SITUATIONAL = "situational"


def sop_scope(sop_number: int, info) -> str:
    """
    判定某條 SOP 對這起事件是「事件觸發」還是「全市態勢」。

    第 3、4、6 條是資料型條款，在同一時間點對所有事件都成立。若全部列成「本事件
    觸發條款」，號誌故障的建議書會出現「觸發第 3 條捷運分流」這種讀起來莫名的內容。
    因此只有與事件直接相關者算事件觸發，其餘列為態勢提醒。
    """
    if sop_number in (2, 5):
        return SCOPE_EVENT
    if sop_number == 3:
        return (
            SCOPE_EVENT
            if info.station == sop_rules.SOP3_STATION or info.is_crowd
            else SCOPE_SITUATIONAL
        )
    if sop_number == 4:
        return SCOPE_EVENT if info.station == sop_rules.SOP4_STATION else SCOPE_SITUATIONAL
    if sop_number == 6:
        # 第 6 條決定本事件通報要用幾種語言，屬於事件處置的一部分
        return SCOPE_EVENT
    return SCOPE_SITUATIONAL


# ---------------------------------------------------------------------------
# SOP 文本讀取與條文原文擷取
# ---------------------------------------------------------------------------

# 條首格式為「N. 標題」，各條之間以整行等號分隔。用條號標題切分而不是切分隔線，
# 否則會把「標題」和「條文內容」切成兩塊（分隔線同時出現在標題上下）。
_CLAUSE_HEADING = re.compile(r"^[ \t]*(\d+)\.[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)
_SEPARATOR_LINE = re.compile(r"^=+$")

_clause_cache: dict[str, dict[int, dict]] = {}


def read_traffic_sop(section: str | None = None) -> dict:
    """優先讀取 S3 SOP，無法讀取時回退本地文本。"""
    sop_file = get_data_path("emergency_traffic_sop.txt")
    if not sop_file.exists():
        return {"error": "SOP 檔案不存在", "sop_text": ""}

    with open(sop_file, encoding="utf-8") as f:
        full_text = f.read()

    source = get_data_source_name("emergency_traffic_sop.txt")
    if not section:
        return {"source": source, "sop_text": full_text}

    clauses = parse_clauses(full_text)

    num_match = re.search(r"(\d+)", str(section))
    if num_match:
        clause = clauses.get(int(num_match.group(1)))
        if clause:
            return {
                "source": source,
                "section_query": section,
                "sop_number": clause["number"],
                "sop_title": clause["title"],
                "sop_text": clause["text"],
                "matched": True,
            }

    needle = str(section).lower()
    matched = [c for c in clauses.values() if needle in c["text"].lower()]
    if matched:
        return {
            "source": source,
            "section_query": section,
            "sop_text": "\n\n".join(c["text"] for c in matched),
            "matched": True,
        }

    return {"source": source, "section_query": section, "sop_text": full_text, "matched": False}


def parse_clauses(full_text: str) -> dict[int, dict]:
    """把 SOP 全文解析成 {條號: {number, title, text}}，標題直接取自條文本身。"""
    if not full_text:
        return {}

    cached = _clause_cache.get(full_text)
    if cached is not None:
        return cached

    headings = list(_CLAUSE_HEADING.finditer(full_text))
    clauses: dict[int, dict] = {}
    for index, heading in enumerate(headings):
        number = int(heading.group(1))
        start = heading.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(full_text)
        lines = full_text[start:end].splitlines()
        # 條文內部與尾端的等號分隔線不是內容，移除後再組回去
        cleaned = [ln for ln in lines if not _SEPARATOR_LINE.match(ln.strip())]
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
        clauses[number] = {
            "number": number,
            "title": heading.group(2).strip(),
            "text": "\n".join(cleaned).strip(),
        }

    _clause_cache.clear()
    _clause_cache[full_text] = clauses
    return clauses


def clause_text(number: int, full_text: str | None = None) -> str:
    """
    擷取指定條號的條文原文。

    回傳原文供 UI 顯示引用依據，讓評審能直接對照 AI 的判定與條文本身。
    """
    if full_text is None:
        full_text = read_traffic_sop().get("sop_text", "")
    clause = parse_clauses(full_text).get(int(number))
    return clause["text"] if clause else ""


def clauses_payload(numbers) -> list[dict]:
    """把條號清單轉成含原文的引用區塊，供建議書與對話回覆附上依據。"""
    data = read_traffic_sop()
    clauses = parse_clauses(data.get("sop_text", ""))
    payload = []
    for number in sorted({int(n) for n in numbers if str(n).isdigit()}):
        clause = clauses.get(number)
        if not clause or not clause["text"]:
            continue
        payload.append({
            "sop_number": number,
            "title": clause["title"] or SOP_TITLES.get(number, ""),
            "text": clause["text"],
            "source": data.get("source", "local"),
        })
    return payload


# ---------------------------------------------------------------------------
# 綜合評估
# ---------------------------------------------------------------------------


def run_assessment(task_payload: dict) -> dict:
    """
    執行法規驗證評估。

    輸出的 max_level 是「這起事件的交通分級」：有對應 RD_ 路段時取該路段的分級
    （人流事件會經 affected_road 對應到車流路段），否則退回全網最高級別。
    另外一併回傳全網最高級別與觸發路段級別，避免單一欄位語意含混。
    """
    task_payload = task_payload if isinstance(task_payload, dict) else {}
    incident = task_payload.get("incident") or {}
    incident = incident if isinstance(incident, dict) else {}
    traffic_data = task_payload.get("traffic_data") or {}
    timestamp = task_payload.get("timestamp") or incident.get("timestamp") or ""

    info = task_payload.get("classification") or sop_rules.classify_incident(incident)
    data_triggers = task_payload.get("data_triggers") or evaluate_data_triggers(timestamp)

    event_id = incident.get("event_id") or "UNKNOWN"

    # --- SOP 第 1 條分級：全部路段都列出，作為完整數據佐證 ---
    congestion_levels = []
    for seg_id, seg_info in traffic_data.items():
        score = seg_info.get("saturation_score", 0)
        level = sop_rules.assess_congestion_level(score)
        congestion_levels.append({
            "segment_id": seg_id,
            "road_name": seg_info.get("road_name", ""),
            "saturation_score": score,
            "level": level,
            "description": sop_rules.level_description(level),
            "is_trigger_segment": sop_rules.is_trigger_segment(seg_id),
            "is_incident_segment": seg_id == info.traffic_segment,
            "data_as_of": seg_info.get("data_as_of"),
        })
    congestion_levels.sort(key=lambda c: c["segment_id"])

    levels = [c["level"] for c in congestion_levels]
    network_max_level = "A" if "A" in levels else ("B" if "B" in levels else "Normal")

    incident_level_entry = next(
        (c for c in congestion_levels if c["is_incident_segment"]), None
    )
    incident_level = incident_level_entry["level"] if incident_level_entry else None
    max_level = incident_level or network_max_level

    trigger_segment_levels = [c for c in congestion_levels if c["is_trigger_segment"]]
    trigger_levels = [c["level"] for c in trigger_segment_levels]
    trigger_max_level = "A" if "A" in trigger_levels else ("B" if "B" in trigger_levels else "Normal")

    # --- SOP 觸發：事件型 + 資料型 ---
    sop2 = check_sop2_trigger(incident, info)
    sop5 = check_sop5_trigger(incident, info)
    triggered_sops = [
        dict(check, scope=sop_scope(check["sop_number"], info))
        for check in (
            sop2,
            data_triggers["sop3"],
            data_triggers["sop4"],
            sop5,
            data_triggers["sop6"],
        )
    ]
    triggered_sops.sort(key=lambda s: s["sop_number"])
    triggered_numbers = [s["sop_number"] for s in triggered_sops if s["triggered"]]
    event_numbers = [
        s["sop_number"]
        for s in triggered_sops
        if s["triggered"] and s["scope"] == SCOPE_EVENT
    ]
    situational_numbers = [
        s["sop_number"]
        for s in triggered_sops
        if s["triggered"] and s["scope"] == SCOPE_SITUATIONAL
    ]

    requires_traffic_routing = info.requires_route_planning and (
        sop2["triggered"] or incident_level == "A"
    )

    summary_parts = []
    if incident_level_entry:
        summary_parts.append(
            f"{incident_level_entry['road_name']}飽和度 "
            f"{round(float(incident_level_entry['saturation_score']) * 100)}%，"
            f"判定 {sop_rules.level_description(incident_level)}"
        )
    if trigger_max_level != "Normal":
        summary_parts.append(
            f"城市應變觸發路段達 {sop_rules.level_description(trigger_max_level)}，"
            f"啟動長綠燈時制（替代道路綠燈 +{sop_rules.GREEN_LIGHT_EXTENSION_PCT}%）"
        )
    for check in triggered_sops:
        if check["triggered"] and check["scope"] == SCOPE_EVENT:
            summary_parts.append(f"觸發 SOP 第 {check['sop_number']} 條：{check['sop_title']}")
    if situational_numbers:
        summary_parts.append(
            "全市態勢同時符合 SOP "
            + "、".join(f"第 {n} 條" for n in situational_numbers)
        )

    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "classification": {
            "kind": info.kind,
            "affected_segment": info.affected_segment,
            "traffic_segment": info.traffic_segment,
            "traffic_segment_source": info.traffic_segment_source,
            "station": info.station,
        },
        "congestion_levels": congestion_levels,
        "incident_segment_level": incident_level,
        "incident_segment": info.traffic_segment,
        "network_max_level": network_max_level,
        "trigger_segment_levels": trigger_segment_levels,
        "trigger_max_level": trigger_max_level,
        "max_level": max_level,
        "triggered_sops": triggered_sops,
        "triggered_sop_numbers": triggered_numbers,
        "event_sop_numbers": event_numbers,
        "situational_sop_numbers": situational_numbers,
        "sop_clauses": clauses_payload([1, *triggered_numbers, 7]),
        "requires_traffic_routing": requires_traffic_routing,
        "requires_comms": True,
        "multilingual_required": data_triggers["multilingual_required"],
        "languages": data_triggers["languages"],
        "roaming_scan": data_triggers["roaming_scan"],
        "summary": "；".join(summary_parts) if summary_parts else "未觸發任何 SOP",
    }
