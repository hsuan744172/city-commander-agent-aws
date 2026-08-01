from backend.agents import traffic_math
from backend.agents.architect import _tool_quality_from


NOW = "2026-05-20 22:15"


def test_data_only_answer_can_be_high_confidence_without_sop_citation():
    confidence = traffic_math.calculate_answer_confidence(
        prompt="目前光復南路的車流狀態如何？",
        response="判斷：目前壅塞。\n\n建議：持續監控。\n\n行動指令：維持觀測。",
        current_time=NOW,
        model_ok=True,
        tools_used=["traffic_status"],
        cited_clause_numbers=[],
        data_as_of=NOW,
    )

    assert confidence["level"] == "high"
    assert confidence["score"] >= 85
    assert "即時車流資料" in confidence["evidence_sources"]
    assert not any("未引用 SOP" in reason for reason in confidence["reasons"])


def test_policy_answer_gains_sop_evidence():
    confidence = traffic_math.calculate_answer_confidence(
        prompt="若國父紀念館站人數增至四萬人，應啟動哪些措施？",
        response="判斷：依據 SOP 第 3 條觸發。\n\n建議：分流。\n\n行動指令：啟動接駁。",
        current_time=NOW,
        model_ok=True,
        tools_used=["crowd_status", "lookup_sop_clause"],
        cited_clause_numbers=[3],
        data_as_of=NOW,
    )

    assert confidence["level"] == "high"
    assert "基地台人流資料" in confidence["evidence_sources"]
    assert "SOP 條文" in confidence["evidence_sources"]


def test_unknown_entities_and_tool_errors_produce_low_confidence():
    confidence = traffic_math.calculate_answer_confidence(
        prompt="請查 RD_TPE_999 與 BS_UNKNOWN 並提出處置。",
        response="判斷：查無資料。\n\n建議：確認編號。\n\n行動指令：不得推測。",
        current_time=NOW,
        model_ok=True,
        tools_used=["evacuation_route", "station_detail"],
        cited_clause_numbers=[],
        data_as_of=NOW,
        tool_error=True,
    )

    assert confidence["level"] == "low"
    assert confidence["score"] < 60
    assert any("RD_TPE_999" in reason for reason in confidence["reasons"])


def test_future_or_out_of_scope_question_is_low_confidence_without_tools():
    confidence = traffic_math.calculate_answer_confidence(
        prompt="請預測 2026-05-21 12:00 的路況與天氣。",
        response="判斷：資料不足。\n\n建議：無法判定。\n\n行動指令：不得推測。",
        current_time=NOW,
        model_ok=True,
        tools_used=[],
        cited_clause_numbers=[],
        data_as_of=NOW,
    )

    assert confidence["level"] == "low"
    assert confidence["score"] < 60
    assert any("晚於目前可用資料" in reason for reason in confidence["reasons"])


def test_model_failure_has_minimal_confidence():
    confidence = traffic_math.calculate_answer_confidence(
        prompt="目前路況？",
        response="AI 無法連線",
        current_time=NOW,
        model_ok=False,
    )

    assert confidence["score"] == 5
    assert confidence["evidence_sources"] == []


def test_tool_quality_reads_only_tool_results():
    quality = _tool_quality_from([
        {
            "role": "user",
            "content": [{
                "toolResult": {
                    "status": "success",
                    "content": [{"text": '{"error":"查無基地台"}'}],
                }
            }],
        }
    ])

    assert quality["has_error"] is True
    assert quality["truncated"] is False
