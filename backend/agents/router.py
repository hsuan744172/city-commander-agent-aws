"""
Traffic-Router Agent — 路網計算與 ETE (嚴格對齊 SOP 第 2、7 條)。

⚠️ 絕不回傳 primary_evacuation_route = null。
"""

from __future__ import annotations

from backend.agents.traffic_math import calculate_ete, calculate_optimal_route


def run_routing(task_payload: dict) -> dict:
    """執行路網計算與 ETE 估算。"""
    task_payload = task_payload if isinstance(task_payload, dict) else {}
    incident = task_payload.get("incident") or {}
    incident = incident if isinstance(incident, dict) else {}
    affected_segment_ids = task_payload.get("affected_segment_ids") or []
    timestamp = task_payload.get("timestamp") or incident.get("timestamp") or ""

    event_id = incident.get("event_id") or "UNKNOWN"
    incident_segment_id = incident.get("affected_segment") or ""
    severity = incident.get("severity") or "Medium"
    errors: list[str] = []

    # --- 1. 路徑計算 (SOP 第 2 條) ---
    route_recommendation = None
    incident_name = ""
    signal_suggestions = []

    if incident_segment_id.startswith("RD_"):
        route_result = calculate_optimal_route(incident_segment_id, timestamp)
        route_result = route_result if isinstance(route_result, dict) else {"error": "計算回傳 None"}

        if "error" in route_result:
            errors.append(f"路徑計算失敗: {route_result['error']}")
        else:
            incident_name = route_result.get("incident_name", "")
            primary = route_result.get("primary_route")

            if primary and isinstance(primary, dict):
                sat = primary.get("saturation_score") or 0
                congestion_note = route_result.get("congestion_note", "")

                route_recommendation = {
                    "primary_route_id": primary.get("segment_id", ""),
                    "primary_route_name": primary.get("name", ""),
                    "capacity_vph": primary.get("capacity_vph", 0),
                    "current_saturation": sat,
                    "is_congested": sat >= 0.85,
                    "selection_reason": route_result.get("selection_reason", ""),
                    "congestion_note": congestion_note,
                    "secondary_routes": route_result.get("secondary_routes", []),
                }

                # 號誌建議
                action_note = congestion_note if sat >= 0.85 else ""
                signal_suggestions.append({
                    "segment_id": primary.get("segment_id", ""),
                    "road_name": primary.get("name", ""),
                    "action": "綠燈配時 +25%（長綠燈時制）",
                    "current_saturation": sat,
                    "note": action_note,
                })

    # --- 2. ETE 計算 (SOP 第 7 條) ---
    ete_result = None

    if not affected_segment_ids and incident_segment_id.startswith("RD_"):
        affected_segment_ids = [incident_segment_id]

    if affected_segment_ids:
        ete_data = calculate_ete(severity, affected_segment_ids, timestamp)
        ete_data = ete_data if isinstance(ete_data, dict) else {"error": "ETE 計算回傳 None"}

        if "error" in ete_data:
            errors.append(f"ETE 計算失敗: {ete_data['error']}")
        else:
            ete_result = {
                "ete_minutes": ete_data.get("ete_minutes", 0),
                "severity": ete_data.get("severity", ""),
                "base_clearance_minutes": ete_data.get("base_clearance_minutes", 0),
                "congestion_penalty_minutes": ete_data.get("congestion_penalty_minutes", 0),
                "avg_saturation_score": ete_data.get("avg_saturation_score", 0),
                "formula": ete_data.get("formula", ""),
                "affected_segments_count": ete_data.get("affected_segments_found", 0),
                "calculation_source": "SOP 第 7 條公式",
            }

    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "incident_segment_id": incident_segment_id,
        "incident_name": incident_name,
        "route_recommendation": route_recommendation,
        "ete_result": ete_result,
        "signal_suggestions": signal_suggestions,
        "errors": errors,
    }
