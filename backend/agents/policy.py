"""
SOP-Policy Agent — 法規驗證與級別判定。

職責：
  1. 判定擁塞級別 (A/B/Normal)
  2. 判定 SOP 2/3/5 觸發條件
  3. 讀取本地 SOP 文本
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOP_FILE = PROJECT_ROOT / "data" / "emergency_traffic_sop.txt"


def assess_congestion_level(saturation_score: float) -> str:
    if saturation_score >= 0.95:
        return "A"
    elif saturation_score >= 0.85:
        return "B"
    return "Normal"


def check_sop2_trigger(incident: dict) -> dict:
    """SOP 第 2 條：車禍與路障應變。"""
    status = incident.get("status") or ""
    severity = incident.get("severity") or ""
    affected = incident.get("affected_segment") or ""

    triggered = (
        status in {"Closed", "Blocked", "Restricted"}
        and severity in {"High", "Critical"}
        and affected.startswith("RD_")
    )

    return {
        "sop_number": 2,
        "sop_title": "車禍與路障應變",
        "triggered": triggered,
        "reason": f"status={status}, severity={severity}, segment={affected}",
        "evidence": {"status": status, "severity": severity, "affected_segment": affected},
    }


def check_sop3_trigger(incident: dict, crowd_data: dict | None = None) -> dict:
    """SOP 第 3 條：捷運與接駁分流。"""
    affected = incident.get("affected_segment") or ""

    if affected != "BS_MRT_BL17" and "BS_MRT_BL17" not in str(incident):
        return {"sop_number": 3, "sop_title": "捷運與接駁分流", "triggered": False, "reason": "事件未影響 BS_MRT_BL17"}

    growth_rate = (crowd_data or {}).get("growth_rate", 0)
    user_count = (crowd_data or {}).get("user_count", 0)
    triggered = growth_rate > 0.30 or user_count > 25000

    return {
        "sop_number": 3,
        "sop_title": "捷運與接駁分流",
        "triggered": triggered,
        "reason": f"Growth_Rate={growth_rate:.2f}, User_Count={user_count}",
        "evidence": {"growth_rate": growth_rate, "user_count": user_count},
    }


def check_sop5_trigger(incident: dict) -> dict:
    """SOP 第 5 條：號誌故障應變。"""
    event_type = incident.get("type") or ""
    description = incident.get("description") or ""

    triggered = event_type == "Power_Failure" or any(kw in description for kw in ["號誌失效", "號誌故障", "故障"])

    return {
        "sop_number": 5,
        "sop_title": "號誌故障應變",
        "triggered": triggered,
        "reason": f"type={event_type}, keywords={'found' if triggered else 'not found'}",
        "evidence": {"type": event_type},
    }


def read_traffic_sop(section: str | None = None) -> dict:
    """讀取本地 SOP 文本。"""
    if not SOP_FILE.exists():
        return {"error": "SOP 檔案不存在", "sop_text": ""}

    with open(SOP_FILE, encoding="utf-8") as f:
        full_text = f.read()

    if not section:
        return {"source": "local_file", "sop_text": full_text}

    # 條號搜尋
    num_match = re.search(r"(\d+)", section)
    if num_match:
        num = num_match.group(1)
        parts = full_text.split("=" * 10)
        for part in parts:
            if f"{num}." in part or f"第{num}條" in part.replace(" ", ""):
                return {"source": "local_file", "section_query": section, "sop_text": part.strip(), "matched": True}

    # 關鍵字搜尋
    parts = full_text.split("=" * 10)
    matched = [p.strip() for p in parts if p.strip() and section.lower() in p.lower()]
    if matched:
        return {"source": "local_file", "section_query": section, "sop_text": "\n\n".join(matched), "matched": True}

    return {"source": "local_file", "section_query": section, "sop_text": full_text, "matched": False}


def run_assessment(task_payload: dict) -> dict:
    """執行法規驗證評估。"""
    task_payload = task_payload if isinstance(task_payload, dict) else {}
    incident = task_payload.get("incident") or {}
    incident = incident if isinstance(incident, dict) else {}
    traffic_data = task_payload.get("traffic_data") or {}
    crowd_data = task_payload.get("crowd_data")
    timestamp = task_payload.get("timestamp") or incident.get("timestamp") or ""

    event_id = incident.get("event_id") or "UNKNOWN"

    # 擁塞級別
    congestion_levels = []
    for seg_id, seg_info in traffic_data.items():
        score = seg_info.get("saturation_score", 0)
        level = assess_congestion_level(score)
        congestion_levels.append({
            "segment_id": seg_id,
            "road_name": seg_info.get("road_name", ""),
            "saturation_score": score,
            "level": level,
            "description": {"A": "A 級癱瘓", "B": "B 級壅擠"}.get(level, "正常"),
        })

    levels = [cl["level"] for cl in congestion_levels]
    max_level = "A" if "A" in levels else ("B" if "B" in levels else "Normal")

    # SOP 觸發
    triggered_sops = [
        check_sop2_trigger(incident),
        check_sop3_trigger(incident, crowd_data),
        check_sop5_trigger(incident),
    ]

    triggered_numbers = [s["sop_number"] for s in triggered_sops if s["triggered"]]
    requires_traffic_routing = max_level == "A" or any(n in triggered_numbers for n in [2, 3, 5])

    # Summary
    summary_parts = []
    if max_level == "A":
        summary_parts.append("達 A 級癱瘓，啟動全面應變")
    elif max_level == "B":
        summary_parts.append("達 B 級壅擠，啟動長綠燈時制")
    for s in triggered_sops:
        if s["triggered"]:
            summary_parts.append(f"觸發 SOP 第 {s['sop_number']} 條：{s['sop_title']}")

    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "congestion_levels": congestion_levels,
        "triggered_sops": triggered_sops,
        "max_level": max_level,
        "requires_traffic_routing": requires_traffic_routing,
        "requires_comms": True,
        "summary": "；".join(summary_parts) if summary_parts else "未觸發任何 SOP",
    }
