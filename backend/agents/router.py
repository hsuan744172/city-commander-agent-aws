"""
Traffic-Router Agent — 路網計算與 ETE (嚴格對齊 SOP 第 1、2、7 條)。

職責：
  1. SOP 第 2 條：主／次疏散路徑篩選，並保留每個候選的排除理由
  2. SOP 第 7 條：ETE，受影響路段一律由 traffic_math.affected_segments_for_ete 決定
  3. SOP 第 1 條：長綠燈時制（替代道路綠燈 +25%）與警力淨空路口

⚠️ 絕不回傳 primary_evacuation_route = null。
⚠️ 所有數值計算都在 traffic_math，這裡只組裝。
"""

from __future__ import annotations

from backend.agents import sop_rules, traffic_math


def run_routing(task_payload: dict) -> dict:
    """
    執行路網計算與 ETE 估算。

    payload：
      incident        事件本體
      classification  sop_rules.classify_incident 的結果（未提供時自行分類）
      timestamp       套用的模擬時間
      plan_signals    是否產出 SOP 第 1 條號誌／警力處置（預設 True）
    """
    task_payload = task_payload if isinstance(task_payload, dict) else {}
    incident = task_payload.get("incident") or {}
    incident = incident if isinstance(incident, dict) else {}
    timestamp = task_payload.get("timestamp") or incident.get("timestamp") or ""
    info = task_payload.get("classification") or sop_rules.classify_incident(incident)
    plan_signals = task_payload.get("plan_signals", True)

    event_id = incident.get("event_id") or "UNKNOWN"
    incident_location = incident.get("location") or ""
    severity = info.severity or "Medium"
    errors: list[str] = []

    # 車流評估路段：人流事件會經 affected_road 對應到 RD_ 路段
    traffic_segment = info.traffic_segment
    incident_name = traffic_math.segment_name(traffic_segment) if traffic_segment else ""

    # --- 1. 替代路徑 (SOP 第 2 條)：只有 RD_ 路段的車禍／路障需要重規劃 ---
    route_recommendation = None
    route_analysis = None
    route_result: dict = {}

    if info.requires_route_planning and traffic_segment:
        route_result = traffic_math.calculate_optimal_route(
            traffic_segment, timestamp, incident_location
        )
        route_result = route_result if isinstance(route_result, dict) else {"error": "計算回傳 None"}

        if "error" in route_result:
            errors.append(f"路徑計算失敗: {route_result['error']}")
            route_result = {}
        else:
            incident_name = route_result.get("incident_name", incident_name)
            primary = route_result.get("primary_route")

            if primary and isinstance(primary, dict):
                saturation = primary.get("saturation_score")
                route_recommendation = {
                    "primary_route_id": primary.get("segment_id", ""),
                    "primary_route_name": primary.get("name", ""),
                    "capacity_vph": primary.get("capacity_vph", 0),
                    "current_saturation": saturation,
                    "is_congested": bool(primary.get("is_congested")),
                    "is_upstream": bool(primary.get("is_upstream")),
                    "is_intersecting": bool(primary.get("is_intersecting")),
                    "selection_tier": route_result.get("selection_tier"),
                    "selection_reason": route_result.get("selection_reason", ""),
                    "congestion_note": route_result.get("congestion_note", ""),
                    "secondary_routes": route_result.get("secondary_routes", []),
                    "excluded_routes": route_result.get("excluded_routes", []),
                }

            # 判定依據展示：候選評估與上下游判定方法一併輸出，
            # 讓「為何排除特定替代道路」有結構化證據可呈現。
            route_analysis = {
                "incident_segment_id": traffic_segment,
                "incident_name": incident_name,
                "flow_direction": route_result.get("flow_direction", ""),
                "intersections": route_result.get("intersections", []),
                "upstream_resolution": route_result.get("upstream_resolution", {}),
                "selection_tier": route_result.get("selection_tier"),
                "candidates": route_result.get("all_candidates", []),
                "min_capacity_vph": sop_rules.SOP2_MIN_CAPACITY_VPH,
                "data_as_of": route_result.get("data_as_of"),
            }

    # --- 2. ETE (SOP 第 7 條)：受影響路段的定義只有一處 ---
    ete_result = None
    affected_segment_ids: list[str] = []

    if traffic_segment:
        affected_segment_ids = traffic_math.affected_segments_for_ete(
            traffic_segment, route_result
        )
        ete_data = traffic_math.calculate_ete(severity, affected_segment_ids, timestamp)
        ete_data = ete_data if isinstance(ete_data, dict) else {"error": "ETE 計算回傳 None"}

        if "error" in ete_data:
            errors.append(f"ETE 計算失敗: {ete_data['error']}")
        else:
            ete_result = {
                "ete_minutes": ete_data.get("ete_minutes", 0),
                "severity": ete_data.get("severity", ""),
                "base_clearance_minutes": ete_data.get("base_clearance_minutes", 0),
                "congestion_penalty_minutes": ete_data.get("congestion_penalty_minutes", 0),
                "avg_saturation_score": ete_data.get("avg_saturation_score"),
                "saturation_data_available": ete_data.get("saturation_data_available", False),
                "note": ete_data.get("note", ""),
                "formula": ete_data.get("formula", ""),
                "affected_segment_ids": ete_data.get("affected_segment_ids", []),
                "affected_segments": ete_data.get("affected_segments", []),
                "affected_segments_count": ete_data.get("affected_segments_found", 0),
                "affected_segments_definition": (
                    "事故路段 + 主疏散路段 + 次要疏散路段"
                    if route_recommendation
                    else "事故路段（本事件依 SOP 不做替代路徑重規劃）"
                ),
                "calculation_source": "SOP 第 7 條公式",
                "data_as_of": ete_data.get("data_as_of"),
            }
    else:
        errors.append("事件未對應到任何 RD_ 車流路段，略過 ETE 與路徑計算")

    # --- 3. 號誌配時處置 ---
    # 只處理這起事件自己的路段。全市觸發路段的常態長綠燈時制屬於「主動偵測」，
    # 由儀表板 (main._build_status) 產出，不塞進單一事件的建議書裡重複。
    #
    # 號誌故障事件不套用長綠燈時制：號誌已失效，SOP 第 5 條要的是人工指揮與警力，
    # 對故障路段下配時指令沒有意義。
    signal_plans: list[dict] = []
    if plan_signals and traffic_segment and not info.is_signal_failure:
        duration = (ete_result or {}).get("ete_minutes")
        primary_id = (route_recommendation or {}).get("primary_route_id", "")
        plan = traffic_math.build_signal_plan(
            traffic_segment, timestamp, duration, primary_id
        )
        if plan and "error" not in plan and plan.get("adjustments"):
            signal_plans.append(plan)

    # 向後相容：既有前端讀 signal_adjustments 的扁平清單
    signal_suggestions = []
    for plan in signal_plans:
        for adjustment in plan.get("adjustments", []):
            signal_suggestions.append({
                "segment_id": adjustment["segment_id"],
                "road_name": adjustment["road_name"],
                "action": adjustment["action"],
                "current_saturation": adjustment["current_saturation"],
                "triggered_by": plan["road_name"],
                "window": plan.get("window", ""),
                "note": (route_recommendation or {}).get("congestion_note", "")
                if adjustment.get("is_primary_route")
                else "",
            })

    # --- 4. 導航更新發布（命題要求） ---
    # 專案沒有連接商用導航供應商，因此明確標示為模擬發布；內容仍是可直接交付
    # 導航介面的結構化封閉路段、主次疏散與排除理由，避免只停留在文字建議。
    if route_recommendation:
        navigation_update = {
            "status": "simulated_published",
            "simulated": True,
            "published_at": timestamp,
            "event_id": event_id,
            "closed_segment_id": traffic_segment,
            "closed_segment_name": incident_name,
            "primary_route": {
                "segment_id": route_recommendation.get("primary_route_id", ""),
                "name": route_recommendation.get("primary_route_name", ""),
            },
            "secondary_routes": [
                {"segment_id": route.get("segment_id", ""), "name": route.get("name", "")}
                for route in route_recommendation.get("secondary_routes", [])
            ],
            "excluded_routes": [
                {
                    "segment_id": route.get("segment_id", ""),
                    "name": route.get("name", ""),
                    "reason": route.get("reason", ""),
                }
                for route in route_recommendation.get("excluded_routes", [])
            ],
        }
    else:
        navigation_update = {
            "status": "not_applicable",
            "simulated": True,
            "published_at": timestamp,
            "event_id": event_id,
            "reason": "本事件依 SOP 不需替代路徑重規劃",
        }

    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "incident_segment_id": traffic_segment,
        "incident_name": incident_name,
        "traffic_segment_source": info.traffic_segment_source,
        "route_recommendation": route_recommendation,
        "route_analysis": route_analysis,
        "ete_result": ete_result,
        "affected_segment_ids": affected_segment_ids,
        "signal_plans": signal_plans,
        "signal_suggestions": signal_suggestions,
        "navigation_update": navigation_update,
        "errors": errors,
    }
