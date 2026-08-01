"""SOP 判定與公眾通報的黃金案例（不呼叫 Bedrock）。"""

from __future__ import annotations

import pytest

from backend.agents import comms, policy, router, sop_rules

from .test_sop_rules import ACCIDENT, CROWD, SIGNAL

ACCIDENT_TIME = "2026-05-20 22:10"
CROWD_TIME = "2026-05-20 22:20"
SIGNAL_TIME = "2026-05-20 22:30"


@pytest.fixture(autouse=True)
def strict_as_of(monkeypatch):
    monkeypatch.setenv("SIM_DATA_MODE", "asof")


# --- SOP 第 2 條觸發 -----------------------------------------------------------


def test_sop2_requires_all_three_conditions():
    assert policy.check_sop2_trigger(ACCIDENT)["triggered"]
    # 人流事件的 affected_segment 是 BS_，依 SOP 改由第 3 條處理
    assert not policy.check_sop2_trigger(CROWD)["triggered"]


@pytest.mark.parametrize(
    "override",
    [
        {"status": "Caution"},      # 狀態不在 {Closed, Blocked, Restricted}
        {"severity": "Medium"},     # 嚴重度不在 {High, Critical}
        {"affected_segment": "BS_MRT_BL17"},
    ],
)
def test_sop2_not_triggered_when_any_condition_fails(override):
    check = policy.check_sop2_trigger({**ACCIDENT, **override})
    assert not check["triggered"]
    assert check["reason"]


# --- SOP 第 3、4、6 條資料型觸發 -----------------------------------------------


def test_sop3_triggers_on_user_count_without_any_incident():
    """第 3 條是純資料條件，儀表板不需要事件注入就該預警。"""
    check = policy.check_sop3_trigger("2026-05-20 22:00")
    assert check["triggered"]
    assert check["evidence"]["user_count"] > sop_rules.SOP3_USER_COUNT_THRESHOLD
    assert any("過站不停" in a for a in check["actions"])
    assert any("BL18" in a for a in check["actions"])


def test_sop4_dome_dismissal_triggers_and_cascades_to_sop3():
    """歷史峰值 40,000 >= 30,000 且當前增幅 -31% <= -20% → 散場啟動並連動第 3 條。"""
    check = policy.check_sop4_trigger("2026-05-20 22:00")
    assert check["triggered"]
    assert check["evidence"]["peak_user_count"] == 40000
    assert check["cascades_to"] == [3]


def test_sop4_not_triggered_before_crowd_declines():
    check = policy.check_sop4_trigger("2026-05-20 19:00")
    assert not check["triggered"]


def test_sop6_triggers_from_citywide_scan():
    check = policy.check_sop6_trigger(SIGNAL_TIME)
    assert check["triggered"]
    assert check["languages"] == list(sop_rules.SOP6_LANGUAGES)
    assert check["evidence"]["scope"] == "全資料集所有基地台"
    assert check["evidence"]["trigger_stations"]


def test_evaluate_data_triggers_cascade_keeps_sop3_actions():
    triggers = policy.evaluate_data_triggers("2026-05-20 22:00")
    assert set(triggers["triggered_numbers"]) >= {3, 4, 6}
    assert triggers["multilingual_required"]


# --- 條文原文擷取 --------------------------------------------------------------


@pytest.mark.parametrize("number", [1, 2, 3, 4, 5, 6, 7])
def test_every_clause_can_be_extracted_with_body(number):
    text = policy.clause_text(number)
    assert text.startswith(f"{number}. ")
    # 只抓到標題不算，必須含條文內容
    assert len(text.splitlines()) > 1


def test_clauses_payload_dedupes_and_sorts():
    payload = policy.clauses_payload([7, 2, 2, "x"])
    assert [c["sop_number"] for c in payload] == [2, 7]


# --- 事件與態勢分流 -----------------------------------------------------------


def _assess(incident, timestamp):
    info = sop_rules.classify_incident(incident)
    triggers = policy.evaluate_data_triggers(timestamp)
    traffic_data = {}
    from backend.agents.architect import _load_traffic_data

    traffic_data = _load_traffic_data(timestamp)
    return policy.run_assessment({
        "incident": incident,
        "classification": info,
        "traffic_data": traffic_data,
        "data_triggers": triggers,
        "timestamp": timestamp,
    })


def test_signal_failure_does_not_claim_mrt_clause_as_its_own_trigger():
    """
    第 3、4 條在同一時間對所有事件都成立，但號誌故障的建議書不該寫
    「本事件觸發捷運分流」。這類條款應歸入全市態勢。
    """
    result = _assess(SIGNAL, SIGNAL_TIME)
    assert 5 in result["event_sop_numbers"]
    assert 3 in result["situational_sop_numbers"]
    assert 3 not in result["event_sop_numbers"]


def test_crowd_event_owns_sop3():
    result = _assess(CROWD, CROWD_TIME)
    assert 3 in result["event_sop_numbers"]


def test_crowd_event_grading_uses_affected_road():
    """人流事件的交通分級來自 affected_road，而非一律回報「正常」。"""
    result = _assess(CROWD, CROWD_TIME)
    assert result["incident_segment"] == "RD_TPE_001"
    assert result["incident_segment_level"] == "A"
    assert result["max_level"] == "A"


def test_assessment_reports_network_and_trigger_levels_separately():
    result = _assess(SIGNAL, SIGNAL_TIME)
    assert result["incident_segment_level"] == "B"      # 松高路
    assert result["network_max_level"] == "A"           # 全網有 A 級
    assert result["trigger_max_level"] == "A"           # 觸發路段達 A 級


# --- 公眾通報 -----------------------------------------------------------------


def _comms_for(incident, timestamp):
    info = sop_rules.classify_incident(incident)
    routing = router.run_routing({
        "incident": incident,
        "classification": info,
        "timestamp": timestamp,
    })
    return info, routing, comms.run_comms({
        "incident": incident,
        "classification": info,
        "routing_result": routing,
        "sop6": policy.check_sop6_trigger(timestamp),
        "nearby_stations": [],
        "timestamp": timestamp,
    })


def test_accident_cms_matches_sop_sentence_pattern():
    """SOP 第 2 條 (b) 明訂句式，逐字不改。"""
    _, routing, result = _comms_for(ACCIDENT, ACCIDENT_TIME)
    ete = int(round(routing["ete_result"]["ete_minutes"]))
    zh = next(m for m in result["messages"] if m["language"] == "zh-TW")
    assert zh["cms_text"] == f"光復南路封閉，請改道 市民大道四段，預計延誤 {ete} 分鐘"


def test_signal_failure_cms_uses_segment_name_not_location_text():
    """
    location 欄位本身含「號誌故障」字樣，若直接代入會產生
    「…路燈號誌故障 號誌故障」的重複贅句。CMS 一律用路段全名。
    """
    _, _, result = _comms_for(SIGNAL, SIGNAL_TIME)
    zh = next(m for m in result["messages"] if m["language"] == "zh-TW")
    assert zh["cms_text"] == "松高路 號誌故障，請依現場指揮通行"
    # 不得出現相鄰重複，也不得把含「號誌故障」字樣的 location 原文代進句子
    assert "號誌故障號誌故障" not in zh["sms_text"]
    assert SIGNAL["location"] not in zh["sms_text"]
    assert "松高路號誌故障" in zh["sms_text"]


def test_all_official_events_produce_four_languages():
    """三個官方事件在其發生時間全市都有站點超標，都必須產出四語。"""
    for incident, timestamp in (
        (ACCIDENT, ACCIDENT_TIME),
        (CROWD, CROWD_TIME),
        (SIGNAL, SIGNAL_TIME),
    ):
        _, _, result = _comms_for(incident, timestamp)
        assert result["trigger_sop6"], incident["event_id"]
        assert [m["language"] for m in result["messages"]] == list(sop_rules.SOP6_LANGUAGES)


def test_public_sms_covers_all_four_required_points():
    for incident, timestamp in (
        (ACCIDENT, ACCIDENT_TIME),
        (CROWD, CROWD_TIME),
        (SIGNAL, SIGNAL_TIME),
    ):
        _, _, result = _comms_for(incident, timestamp)
        assert result["message_requirements"] == {
            "事故位置": True,
            "改道指引": True,
            "預計延誤時間": True,
            "求援或避開提醒": True,
        }, incident["event_id"]
        zh = next(m for m in result["messages"] if m["language"] == "zh-TW")
        # 求援或避開提醒：至少含一組緊急聯絡電話
        assert any(number in zh["sms_text"] for number in ("1999", "110", "119"))


def test_no_errors_for_official_events():
    for incident, timestamp in (
        (ACCIDENT, ACCIDENT_TIME),
        (CROWD, CROWD_TIME),
        (SIGNAL, SIGNAL_TIME),
    ):
        _, routing, result = _comms_for(incident, timestamp)
        assert routing["errors"] == [], incident["event_id"]
        assert result["errors"] == [], incident["event_id"]


# --- router 一致性 ------------------------------------------------------------


def test_signal_failure_gets_no_green_light_plan():
    """號誌已失效，對故障路段下配時指令沒有意義（SOP 第 5 條要的是人工指揮）。"""
    _, routing, _ = _comms_for(SIGNAL, SIGNAL_TIME)
    assert routing["signal_plans"] == []
    assert routing["ete_result"]["ete_minutes"] == pytest.approx(41.0, abs=0.01)


def test_router_exposes_candidate_analysis_for_explainability():
    _, routing, _ = _comms_for(ACCIDENT, ACCIDENT_TIME)
    analysis = routing["route_analysis"]
    assert analysis["candidates"]
    assert analysis["upstream_resolution"]["method"] == "事故點定位"
    assert routing["route_recommendation"]["excluded_routes"]
