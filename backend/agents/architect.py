"""
Architect Commander Agent — 總指揮 (FastAPI 同 process 版)。
協調 Policy / Router / Comms，彙整交控中心建議書。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from backend.agents.comms import run_comms
from backend.agents.policy import run_assessment
from backend.agents.router import run_routing

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LIVE_INCIDENTS_FILE = DATA_DIR / "live_incidents.json"
TRAFFIC_FLOW_CSV = DATA_DIR / "city_traffic_flow.csv"
ROAD_NETWORK_JSON = DATA_DIR / "road_network_geometry.json"
CROWD_DENSITY_CSV = DATA_DIR / "signaling_crowd_density.csv"


def _load_incidents(event: dict | None = None) -> list[dict]:
    if event and isinstance(event, dict) and "incidents" in event:
        incidents = event["incidents"]
        return incidents if isinstance(incidents, list) else []
    if LIVE_INCIDENTS_FILE.exists():
        with open(LIVE_INCIDENTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def _load_traffic_data(timestamp: str | None = None) -> dict:
    if not TRAFFIC_FLOW_CSV.exists():
        return {}
    df = pd.read_csv(TRAFFIC_FLOW_CSV, parse_dates=["Timestamp"])
    if df["Saturation_Score"].dtype == object:
        df["Saturation_Score"] = df["Saturation_Score"].str.rstrip("%").astype(float)
        df.loc[df["Saturation_Score"] > 1, "Saturation_Score"] /= 100

    ts = pd.Timestamp(timestamp) if timestamp else df["Timestamp"].max()
    time_df = df[df["Timestamp"] == ts]
    if time_df.empty:
        idx = (df["Timestamp"] - ts).abs().argsort().iloc[0]
        time_df = df.iloc[[idx]]

    result = {}
    for _, row in time_df.iterrows():
        result[row["Segment_ID"]] = {
            "road_name": row["Road_Name"],
            "saturation_score": float(row["Saturation_Score"]),
            "avg_speed": float(row["Avg_Speed"]),
            "vehicle_count": int(row["Vehicle_Count"]),
            "lane_status": row["Lane_Status"],
        }
    return result


def _load_crowd_data(bs_id: str, timestamp: str | None = None) -> dict | None:
    if not CROWD_DENSITY_CSV.exists():
        return None
    df = pd.read_csv(CROWD_DENSITY_CSV, parse_dates=["Timestamp"])
    if df["Roaming_User_Pct"].dtype == object:
        df["Roaming_User_Pct"] = df["Roaming_User_Pct"].str.rstrip("%").astype(float) / 100

    bs_df = df[df["BS_ID"] == bs_id]
    if bs_df.empty:
        return None

    ts = pd.Timestamp(timestamp) if timestamp else bs_df["Timestamp"].max()
    row = bs_df[bs_df["Timestamp"] == ts]
    if row.empty:
        idx = (bs_df["Timestamp"] - ts).abs().argsort().iloc[0]
        row = bs_df.iloc[[idx]]
    if row.empty:
        return None

    r = row.iloc[0]
    return {"bs_id": bs_id, "user_count": int(r["User_Count"]), "growth_rate": float(r["Growth_Rate"]), "roaming_user_pct": float(r["Roaming_User_Pct"])}


def _get_nearby_stations(segment_id: str) -> list[str]:
    if not ROAD_NETWORK_JSON.exists():
        return []
    with open(ROAD_NETWORK_JSON, encoding="utf-8") as f:
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
    timestamp = incident.get("timestamp") or ""
    affected_segment = incident.get("affected_segment") or ""

    # Phase 1: Policy
    traffic_data = _load_traffic_data(timestamp)
    crowd_data = _load_crowd_data(affected_segment, timestamp) if affected_segment.startswith("BS_") else None

    policy_result = run_assessment({"incident": incident, "traffic_data": traffic_data, "crowd_data": crowd_data, "timestamp": timestamp})
    policy_result = policy_result if isinstance(policy_result, dict) else {}

    # Phase 2: Routing
    routing_result = {}
    if policy_result.get("requires_traffic_routing"):
        affected_ids = _get_affected_ids(incident, traffic_data)
        routing_result = run_routing({"incident": incident, "affected_segment_ids": affected_ids, "timestamp": timestamp})
        routing_result = routing_result if isinstance(routing_result, dict) else {}

    # Phase 3: Comms
    nearby = _get_nearby_stations(affected_segment)
    if affected_segment.startswith("BS_") and affected_segment not in nearby:
        nearby.append(affected_segment)

    comms_result = run_comms({"incident": incident, "routing_result": routing_result, "nearby_stations": nearby, "timestamp": timestamp})
    comms_result = comms_result if isinstance(comms_result, dict) else {}

    # Assemble advisory
    return _assemble_advisory(incident, policy_result, routing_result, comms_result, timestamp)


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
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
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


def run_commander(event: dict | None = None, session_id: str = "") -> dict:
    """總指揮主流程。"""
    incidents = _load_incidents(event)
    if not incidents:
        return {"status": "no_incidents", "message": "無事件需要處理", "advisories": []}

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
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_incidents": len(incidents),
        "processed": len([a for a in advisories if "error" not in a]),
        "failed": len([a for a in advisories if "error" in a]),
        "advisories": advisories,
    }


def run_what_if(prompt: str, session_id: str = "") -> dict:
    """
    What-if 情境問答 — 支援 Bedrock 或 Gemini。

    環境變數：
      - LLM_PROVIDER: "bedrock" 或 "gemini" (預設 gemini)
      - GEMINI_API_KEY: Google AI Studio API Key
      - GEMINI_MODEL_ID: Gemini 模型 (預設 gemini-2.5-flash)
      - BEDROCK_MODEL_ID: Bedrock 模型 (預設 us.anthropic.claude-sonnet-4-20250514)
      - APP_AWS_REGION: AWS 區域
    """
    import os

    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()

    # 讀取 SOP 作為 system context
    from backend.agents.policy import read_traffic_sop
    sop_data = read_traffic_sop()
    sop_text = sop_data.get("sop_text", "")[:3000]

    # 讀取當前路網狀態
    traffic_data = _load_traffic_data()
    traffic_summary = json.dumps(traffic_data, ensure_ascii=False)[:2000]

    system_prompt = f"""你是「城市應變指揮官」，台北市交控中心的 AI 決策顧問。

【身分與口吻】
以交控中心資深長官的專業口吻回答。語氣簡潔、果斷、有權威感。

【嚴格禁止事項】
- 禁止輸出任何 LaTeX 數學符號（如 $...$、\\frac 等）
- 禁止輸出程式碼變數名稱（如 Saturation_Score、capacity_vph）
- 禁止使用 Markdown 程式碼區塊
- 所有數值直接用中文表述（例：「飽和度 95%」而非「Saturation_Score = 0.95」）

【回覆格式要求】
- 字數控制在 500 字以內
- 結構：先判斷 → 再建議 → 最後行動指令
- 時間格式一律 YYYY-MM-DD HH:MM
- 引用 SOP 時標示條號（例：依據 SOP 第 2 條）

【知識基礎】
交通應變標準程序：
{sop_text}

當前路網狀態：
{traffic_summary}
"""

    if provider == "gemini":
        return _call_gemini(prompt, system_prompt, session_id)
    else:
        return _call_bedrock(prompt, system_prompt, session_id)


def _call_gemini(prompt: str, system_prompt: str, session_id: str) -> dict:
    """透過 Google Gemini API 回應。"""
    import os

    import httpx

    api_key = os.environ.get("GEMINI_API_KEY", "")
    model_id = os.environ.get("GEMINI_MODEL_ID", "gemini-2.5-flash")

    if not api_key:
        return {
            "session_id": session_id,
            "prompt": prompt,
            "response": "錯誤：GEMINI_API_KEY 環境變數未設定",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 4096,
        },
    }

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # 解析 Gemini 回應
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            response_text = "".join(p.get("text", "") for p in parts)
        else:
            response_text = "Gemini 未回傳有效內容"

        return {
            "session_id": session_id,
            "prompt": prompt,
            "response": response_text,
            "model": f"gemini/{model_id}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        logger.error(f"Gemini 呼叫失敗: {type(e).__name__}: {e}")
        return {
            "session_id": session_id,
            "prompt": prompt,
            "response": f"Gemini API 錯誤: {type(e).__name__}: {e}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }


def _call_bedrock(prompt: str, system_prompt: str, session_id: str) -> dict:
    """透過 Amazon Bedrock (Strands SDK) 回應。"""
    import os

    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514")
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
