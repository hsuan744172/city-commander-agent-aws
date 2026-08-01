"""SOP 規則層的黃金案例 — 對照 data/emergency_traffic_sop.txt 逐條驗證。

這些測試刻意用命題附的三個官方事件與資料集實際數值，
之後改動判定邏輯若偏離 SOP 原文就會在這裡被擋下來。
"""

from __future__ import annotations

import pytest

from backend.agents import sop_rules

ACCIDENT = {
    "event_id": "TPE_2026_ACC_001",
    "type": "Road_Collapse_Accident",
    "location": "光復南路與忠孝東路口南側",
    "affected_segment": "RD_TPE_002",
    "status": "Closed",
    "severity": "Critical",
    "description": "地下管線爆裂導致路面塌陷並引發三車連環追撞，光復南路南下全線封鎖",
}

CROWD = {
    "event_id": "TPE_2026_EVT_002",
    "type": "Crowd_Surge_Injury",
    "location": "捷運國父紀念館站 5 號出口",
    "affected_segment": "BS_MRT_BL17",
    "affected_road": "RD_TPE_001",
    "status": "Restricted",
    "severity": "High",
    "description": "散場人群推擠受傷，救護車佔用單向車道，人流進站動線中斷",
}

SIGNAL = {
    "event_id": "TPE_2026_EVT_003",
    "type": "Power_Failure",
    "location": "信義威秀/ATT4FUN周邊路燈號誌故障",
    "affected_segment": "RD_TPE_007",
    "status": "Caution",
    "severity": "Medium",
    "description": "信義區部分路段號誌失效，需改由人工交通指揮",
}


# --- SOP 第 1 條 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (0.0, "Normal"),
        (0.84, "Normal"),
        (0.85, "B"),          # 邊界：0.85 <= x < 0.95 為 B 級
        (0.94, "B"),
        (0.95, "A"),          # 邊界：>= 0.95 為 A 級
        (1.0, "A"),
    ],
)
def test_congestion_level_boundaries(score, level):
    assert sop_rules.assess_congestion_level(score) == level


def test_only_two_city_response_trigger_segments():
    """SOP 第 1 條：城市應變觸發路段只有忠孝東路與光復南路。"""
    assert sop_rules.SOP1_TRIGGER_SEGMENTS == ("RD_TPE_001", "RD_TPE_002")
    assert sop_rules.is_trigger_segment("RD_TPE_001")
    assert sop_rules.is_trigger_segment("RD_TPE_002")
    # 基隆路一段在資料集中也會達 A 級，但不是觸發路段，不得啟動應變
    assert not sop_rules.is_trigger_segment("RD_TPE_003")


# --- 事件分類 -----------------------------------------------------------------


def test_classify_road_accident():
    info = sop_rules.classify_incident(ACCIDENT)
    assert info.kind == sop_rules.ROAD_INCIDENT
    assert info.traffic_segment == "RD_TPE_002"
    assert info.traffic_segment_source == "affected_segment"
    assert info.requires_route_planning


def test_classify_crowd_event_uses_affected_road():
    """人流事件經 affected_road 對應車流路段（命題所稱人流↔車流融合）。"""
    info = sop_rules.classify_incident(CROWD)
    assert info.kind == sop_rules.CROWD_INCIDENT
    assert info.station == "BS_MRT_BL17"
    assert info.traffic_segment == "RD_TPE_001"
    assert info.traffic_segment_source == "affected_road"
    # SOP 第 2 條明訂 BS_ 人流類事件改由第 3 條處理，不做替代路徑重規劃
    assert not info.requires_route_planning


def test_classify_signal_failure_takes_precedence():
    info = sop_rules.classify_incident(SIGNAL)
    assert info.kind == sop_rules.SIGNAL_FAILURE
    assert not info.requires_route_planning


def test_bare_failure_keyword_does_not_trigger_signal_failure():
    """只認「號誌失效／號誌故障」，裸『故障』不算，避免誤判。"""
    info = sop_rules.classify_incident({
        "event_id": "X",
        "affected_segment": "RD_TPE_001",
        "type": "Accident",
        "description": "管線爆裂，非號誌相關故障",
    })
    assert info.kind == sop_rules.ROAD_INCIDENT


# --- SOP 第 2 條 (a)(3) 上下游判定 --------------------------------------------


def test_upstream_resolved_from_incident_location_and_flow_direction():
    """
    光復南路事故點在忠孝東路口南側、車流南下，
    因此市民大道四段與忠孝東路四段屬上游，仁愛路四段屬下游。
    """
    intersections = ["市民大道四段", "忠孝東路四段", "仁愛路四段"]
    result = sop_rules.resolve_upstream(
        intersections, "南北向 (事故影響南下車流)", "光復南路與忠孝東路口南側"
    )
    assert result.method == "事故點定位"
    assert result.matched_intersection == "忠孝東路四段"
    assert result.incident_side == "南"
    assert result.downstream_side == "南"
    assert result.is_upstream(intersections.index("市民大道四段"))
    assert result.is_upstream(intersections.index("忠孝東路四段"))
    assert not result.is_upstream(intersections.index("仁愛路四段"))


def test_axis_only_flow_direction_is_not_a_direction():
    """「東西向」只描述軸線，不可被解讀成「西向」。"""
    result = sop_rules.resolve_upstream(["延吉街", "光復南路"], "東西向", "")
    assert result.downstream_side == ""


def test_upstream_falls_back_to_midpoint_and_says_so():
    """位置描述無法定位時退回半段啟發式，並在報告標明方法。"""
    result = sop_rules.resolve_upstream(
        ["市民大道四段", "忠孝東路四段", "仁愛路四段"], "南北向", ""
    )
    assert result.method == "上游半段啟發式"
    assert result.detail


def test_resolve_upstream_handles_empty_intersections():
    result = sop_rules.resolve_upstream([], "", "")
    assert result.upstream_indices == frozenset()


# --- SOP 第 5、7 條常數 -------------------------------------------------------


def test_police_required_two_per_intersection():
    assert sop_rules.police_required(3) == 6
    assert sop_rules.police_required(0) == 0


def test_ete_constants_match_sop_text():
    assert sop_rules.ETE_BASE_CLEARANCE == {"Critical": 60, "High": 40, "Medium": 20}
    assert sop_rules.ETE_SATURATION_BASELINE == 0.5
    assert sop_rules.ETE_SATURATION_FACTOR == 60


def test_sop6_threshold_is_thirty_percent():
    assert sop_rules.SOP6_ROAMING_THRESHOLD == 0.30


def test_thresholds_payload_exposes_frontend_contract():
    payload = sop_rules.thresholds_payload()
    for key in ("level_a", "level_b", "sop1_trigger_segments", "sop6_roaming"):
        assert key in payload
