"""
AI 策略顧問可呼叫的工具集。

為什麼要有這一層：對話顧問原本只拿到一段車流文字摘要，被問到「RD_TPE_003 封閉
主疏散是哪一條」「哪些基地台漫遊超過 30%」只能靠模型自己推，答案可能與確定性
引擎不一致。把 traffic_math / policy 包成工具後，顧問回答時實際呼叫的是同一套
計算，畫面上的建議書與對話回覆不會互相矛盾。

⚠️ 工具一律把「本次對話的模擬時間」寫死在閉包裡，不依賴 ContextVar。
   Strands 可能在別的執行緒跑工具，ContextVar 不保證傳遞。
"""

from __future__ import annotations

import json
from typing import Callable

from strands import tool

from backend.agents import policy, sop_rules, traffic_math

# 工具回傳給模型的內容一律壓成 JSON 字串：模型看得懂，也不會被物件序列化細節影響。
_MAX_TOOL_CHARS = 6000


def _dump(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > _MAX_TOOL_CHARS:
        return text[:_MAX_TOOL_CHARS] + "...(已截斷)"
    return text


def _split_ids(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").replace("，", ",").split(",") if part.strip()]


def build_tools(timestamp: str) -> list[Callable]:
    """建立綁定在指定模擬時間上的工具集合。"""

    ts = timestamp or None

    @tool
    def lookup_sop_clause(clause_number: int) -> str:
        """
        取得交通應變 SOP 指定條號的條文原文。回答時務必引用條號。

        Args:
            clause_number: SOP 條號，1 到 7。
        """
        text = policy.clause_text(int(clause_number))
        if not text:
            return _dump({"error": f"查無 SOP 第 {clause_number} 條"})
        return _dump({"sop_number": int(clause_number), "text": text})

    @tool
    def traffic_status() -> str:
        """查詢當下全路網車流狀態：每個路段的飽和度、車速、車流量與 SOP 第 1 條分級。"""
        return _dump(traffic_math.get_current_traffic_context(ts))

    @tool
    def crowd_status(
        bs_id: str = "",
        user_count: int | None = None,
        growth_rate: float | None = None,
        roaming_user_pct: float | None = None,
    ) -> str:
        """
        查詢當下全基地台人流；若問題包含假設人數、增幅或漫遊率，必須把使用者明示的
        值傳入本工具做確定性判定，不得自行推算未提供欄位。

        Args:
            bs_id: 假設情境的基地台編號；只查全市現況時留空。
            user_count: 使用者明示的假設人數，未提供則留空。
            growth_rate: 使用者明示的假設增幅，使用 0~1；未提供則留空。
            roaming_user_pct: 使用者明示的假設漫遊率，使用 0~1；未提供則留空。
        """
        has_scenario = any(
            value is not None for value in (user_count, growth_rate, roaming_user_pct)
        )
        if has_scenario:
            if not bs_id:
                return _dump({"error": "假設人流情境必須提供基地台編號"})
            return _dump(traffic_math.evaluate_crowd_scenario(
                bs_id,
                ts,
                user_count=user_count,
                growth_rate=growth_rate,
                roaming_user_pct=roaming_user_pct,
            ))
        return _dump(traffic_math.get_current_crowd_context(ts))

    @tool
    def sop_trigger_status() -> str:
        """
        查詢當下由資料驅動的 SOP 條款觸發狀態（第 3 條捷運分流、第 4 條大巨蛋散場、
        第 6 條多語通報），含判定依據數值。
        """
        triggers = policy.evaluate_data_triggers(ts)
        return _dump({
            "查詢時間": triggers["query_timestamp"],
            "資料時間": triggers["data_as_of"],
            "已觸發條款": triggers["triggered_numbers"],
            "多語通報": triggers["multilingual_required"],
            "語言": triggers["languages"],
            "判定明細": [
                {
                    "條號": c["sop_number"],
                    "標題": c["sop_title"],
                    "觸發": c["triggered"],
                    "依據": c["reason"],
                    "建議處置": c.get("actions", []),
                }
                for c in triggers["checks"]
            ],
        })

    @tool
    def evacuation_route(segment_id: str, incident_location: str = "") -> str:
        """
        依 SOP 第 2 條計算指定路段封閉時的主疏散與次要疏散路徑，並回傳每個候選
        替代道路被選用或排除的理由。

        Args:
            segment_id: 事故路段編號，例如 RD_TPE_003。
            incident_location: 事故位置描述，用於判定相交路口的上下游，可留空。
        """
        result = traffic_math.calculate_optimal_route(segment_id, ts, incident_location)
        if "error" in result:
            return _dump(result)
        primary = result["primary_route"]
        return _dump({
            "事故路段": result["incident_name"],
            "主疏散路段": primary.get("name"),
            "主疏散飽和度": primary.get("saturation_score"),
            "主疏散容量": primary.get("capacity_vph"),
            "選擇依據": result["selection_reason"],
            "退階層級": result["selection_tier"],
            "上下游判定": result["upstream_resolution"],
            "次要疏散": [c["name"] for c in result["secondary_routes"]],
            "排除候選": [
                {"路段": c["name"], "理由": c["reason"]} for c in result["excluded_routes"]
            ],
            "壅塞註記": result["congestion_note"],
        })

    @tool
    def recovery_time(
        severity: str,
        incident_segment_id: str,
        incident_location: str = "",
    ) -> str:
        """
        依事故路段先重新計算主、次疏散，再由唯一受影響路段定義計算 ETE。
        模型不得自行傳入或刪減路段清單。

        Args:
            severity: 事故嚴重度，只能是 Critical、High 或 Medium。
            incident_segment_id: 事故路段編號，例如 RD_TPE_002。
            incident_location: 事故位置描述，用於上下游判定，可留空。
        """
        route = traffic_math.calculate_optimal_route(
            incident_segment_id, ts, incident_location,
        )
        if "error" in route:
            return _dump(route)
        affected_ids = traffic_math.affected_segments_for_ete(
            incident_segment_id, route,
        )
        result = traffic_math.calculate_ete(severity, affected_ids, ts)
        return _dump({
            "incident_segment_id": incident_segment_id,
            "primary_route": route.get("primary_route", {}).get("name"),
            "secondary_routes": [
                item.get("name") for item in route.get("secondary_routes", [])
            ],
            "affected_segment_definition": "事故路段 + 主疏散路段 + 次要疏散路段",
            "route_selection_reason": route.get("selection_reason"),
            "ete": result,
        })

    @tool
    def signal_plan(segment_id: str) -> str:
        """
        查詢指定路段的號誌配時與警力處置建議（SOP 第 1 條長綠燈時制與淨空路口，
        或 SOP 第 2 條主疏散長綠燈時制）。

        Args:
            segment_id: 路段編號，例如 RD_TPE_001。
        """
        return _dump(traffic_math.build_signal_plan(segment_id, ts))

    @tool
    def station_detail(bs_id: str) -> str:
        """
        查詢單一基地台的當下人流與歷史峰值，用於 SOP 第 3、4 條判定。

        Args:
            bs_id: 基地台編號，例如 BS_MRT_BL17 或 BS_TPE_DOME。
        """
        return _dump({
            "當下": traffic_math.station_reading(bs_id, ts),
            "歷史": traffic_math.station_history(bs_id, ts),
            "SOP第3條門檻": {
                "人流增幅": sop_rules.SOP3_GROWTH_THRESHOLD,
                "人數": sop_rules.SOP3_USER_COUNT_THRESHOLD,
            },
            "SOP第4條門檻": {
                "歷史峰值": sop_rules.SOP4_PEAK_THRESHOLD,
                "人流增幅": sop_rules.SOP4_DECLINE_THRESHOLD,
            },
        })

    @tool
    def network_geometry() -> str:
        """查詢路網靜態幾何：各路段車流方向、承載容量、相交路段（上游→下游排序）與建議分流方向。"""
        return _dump(traffic_math.get_network_context())

    return [
        lookup_sop_clause,
        traffic_status,
        crowd_status,
        sop_trigger_status,
        evacuation_route,
        recovery_time,
        signal_plan,
        station_detail,
        network_geometry,
    ]


TOOL_NAMES: tuple[str, ...] = (
    "lookup_sop_clause",
    "traffic_status",
    "crowd_status",
    "sop_trigger_status",
    "evacuation_route",
    "recovery_time",
    "signal_plan",
    "station_detail",
    "network_geometry",
)
