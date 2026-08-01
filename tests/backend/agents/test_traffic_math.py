"""traffic_math 的 SOP 第 2、6、7 條計算驗證（使用專案自帶資料集，不呼叫 Bedrock）。"""

from __future__ import annotations

import pytest

from backend.agents import sop_rules, traffic_math

ACCIDENT_TIME = "2026-05-20 22:10"
LATE_TIME = "2026-05-20 22:30"


@pytest.fixture(autouse=True)
def strict_as_of(monkeypatch):
    """一律用 as-of 切片測試，避免插值把驗算變成浮動值。"""
    monkeypatch.setenv("SIM_DATA_MODE", "asof")


# --- SOP 第 2 條 ---------------------------------------------------------------


def test_primary_route_is_upstream_intersecting_lowest_saturation():
    """光復南路封閉 → 主疏散為市民大道四段（唯一上游相交且容量達標者）。"""
    result = traffic_math.calculate_optimal_route(
        "RD_TPE_002", ACCIDENT_TIME, "光復南路與忠孝東路口南側"
    )
    primary = result["primary_route"]
    assert primary["segment_id"] == "RD_TPE_004"
    assert primary["is_intersecting"] and primary["is_upstream"]
    assert result["selection_tier"] == 1
    # 下游相交幹道只列次要疏散
    assert [c["segment_id"] for c in result["secondary_routes"]] == ["RD_TPE_005"]


def test_primary_route_never_appears_in_secondary_routes():
    """主疏散不可同時出現在次要疏散清單（畫面上會像壞掉）。"""
    for segment_id in ("RD_TPE_001", "RD_TPE_002", "RD_TPE_003", "RD_TPE_007"):
        result = traffic_math.calculate_optimal_route(segment_id, LATE_TIME)
        primary_id = result["primary_route"]["segment_id"]
        secondary_ids = [c["segment_id"] for c in result["secondary_routes"]]
        assert primary_id not in secondary_ids, segment_id


def test_low_capacity_alternative_is_excluded_with_reason():
    """延吉街容量 600 < 1000，須被排除且附上理由。"""
    result = traffic_math.calculate_optimal_route("RD_TPE_002", ACCIDENT_TIME)
    excluded = {c["segment_id"]: c for c in result["excluded_routes"]}
    assert "RD_TPE_008" in excluded
    assert not excluded["RD_TPE_008"]["capacity_ok"]
    assert "1000" in excluded["RD_TPE_008"]["reason"]


def test_every_alternative_is_accounted_for():
    """每個 alternative 都要出現在候選表，才能說明排除理由。"""
    network = {s["segment_id"]: s for s in traffic_math._load_road_network()}
    for segment_id, seg in network.items():
        result = traffic_math.calculate_optimal_route(segment_id, LATE_TIME)
        listed = {c["segment_id"] for c in result["all_candidates"]}
        assert set(seg["alternatives"]).issubset(listed), segment_id


def test_route_never_returns_null_primary():
    network = traffic_math._load_road_network()
    for seg in network:
        result = traffic_math.calculate_optimal_route(seg["segment_id"], LATE_TIME)
        assert result["primary_route"] is not None
        assert result["selection_reason"]


def test_unknown_segment_returns_error():
    assert "error" in traffic_math.calculate_optimal_route("RD_NOPE", LATE_TIME)


# --- SOP 第 7 條 ---------------------------------------------------------------


def test_ete_matches_sop_formula():
    """ETE = base_clearance + max(0, (平均飽和度 - 0.5) * 60)。"""
    result = traffic_math.calculate_ete("Critical", ["RD_TPE_002"], ACCIDENT_TIME)
    avg = result["avg_saturation_score"]
    expected = 60 + max(0, (avg - 0.5) * 60)
    assert result["ete_minutes"] == pytest.approx(expected, abs=0.01)
    assert result["saturation_data_available"]


def test_ete_penalty_floors_at_zero():
    """平均飽和度低於 0.5 時壅塞懲罰以 0 計。"""
    result = traffic_math.calculate_ete("Medium", ["RD_TPE_002"], "2026-05-20 20:00")
    assert result["avg_saturation_score"] < 0.5
    assert result["congestion_penalty_minutes"] == 0
    assert result["ete_minutes"] == 20


def test_ete_without_traffic_data_does_not_fabricate_saturation():
    """查無車流量測時不得偷偷代入預設飽和度，須明確標示。"""
    result = traffic_math.calculate_ete("High", ["BS_MRT_BL17"], ACCIDENT_TIME)
    assert result["avg_saturation_score"] is None
    assert result["saturation_data_available"] is False
    assert result["congestion_penalty_minutes"] == 0
    assert result["ete_minutes"] == 40
    assert result["note"]


def test_ete_rejects_unsupported_severity():
    assert "error" in traffic_math.calculate_ete("Low", ["RD_TPE_002"], ACCIDENT_TIME)


def test_affected_segments_definition_is_incident_plus_evacuation_routes():
    """受影響路段 = 事故路段 + 主疏散 + 次要疏散，且不含重複與非 RD_ 項目。"""
    route = traffic_math.calculate_optimal_route(
        "RD_TPE_002", ACCIDENT_TIME, "光復南路與忠孝東路口南側"
    )
    ids = traffic_math.affected_segments_for_ete("RD_TPE_002", route)
    assert ids == ["RD_TPE_002", "RD_TPE_004", "RD_TPE_005"]
    assert len(ids) == len(set(ids))


def test_affected_segments_ignores_station_ids():
    ids = traffic_math.affected_segments_for_ete("BS_MRT_BL17", {})
    assert ids == []


# --- SOP 第 6 條 ---------------------------------------------------------------


def test_roaming_scan_covers_all_stations_not_just_nearby():
    """
    SOP 第 6 條是「任一基地台 >= 30%」。三個官方事件時間點全市都有站點超標，
    因此多語通報必須觸發 — 這是原本只查事故周邊基地台會漏掉的情境。
    """
    for timestamp in ("2026-05-20 22:10", "2026-05-20 22:20", "2026-05-20 22:30"):
        scan = traffic_math.scan_roaming(timestamp)
        assert scan["triggered"], timestamp
        assert scan["languages"] == list(sop_rules.SOP6_LANGUAGES)
        ids = {s["bs_id"] for s in scan["trigger_stations"]}
        assert "BS_TPE_101" in ids
        # 事故路段周邊基地台其實都沒超標，證明判定範圍是全市
        nearby = set(traffic_math.segment_info("RD_TPE_002")["nearby_stations"])
        assert not (ids & nearby)


def test_roaming_values_are_fractions_not_percentages():
    """全系統統一以 0~1 表示漫遊率，顯示字串另外提供。"""
    scan = traffic_math.scan_roaming("2026-05-20 22:30")
    for station in scan["stations"]:
        assert 0.0 <= station["roaming_user_pct"] <= 1.0
        assert station["roaming_user_pct_display"].endswith("%")


# --- SOP 第 4 條：歷史峰值 -----------------------------------------------------


def test_station_history_peak_only_uses_past_measurements():
    """歷史峰值是累積狀態，不得看到查詢時間之後的資料。"""
    early = traffic_math.station_history(sop_rules.SOP4_STATION, "2026-05-20 17:30")
    assert early["peak_user_count"] == 15000

    later = traffic_math.station_history(sop_rules.SOP4_STATION, "2026-05-20 22:00")
    assert later["peak_user_count"] == 40000
    assert later["peak_at"] == "2026-05-20 19:00"
    assert later["current_growth_rate"] <= sop_rules.SOP4_DECLINE_THRESHOLD


# --- SOP 第 1 條：號誌與警力處置 ----------------------------------------------


def test_signal_plan_for_trigger_segment_covers_all_alternatives_and_police():
    """觸發路段依 SOP 第 1 條調整 alternatives 全集，並輸出警力淨空需求。"""
    plan = traffic_math.build_signal_plan("RD_TPE_002", LATE_TIME, 80.0)
    assert plan["scope"] == traffic_math.SIGNAL_SCOPE_SOP1
    adjusted = {a["segment_id"] for a in plan["adjustments"]}
    assert adjusted == set(traffic_math.segment_info("RD_TPE_002")["alternatives"])
    assert plan["police_dispatch"]["officers"] == 6
    assert plan["window"]


def test_signal_plan_for_non_trigger_segment_targets_primary_only():
    """非觸發路段只有 SOP 第 2 條的主疏散長綠燈時制，沒有警力淨空。"""
    plan = traffic_math.build_signal_plan(
        "RD_TPE_003", LATE_TIME, 60.0, primary_route_id="RD_TPE_006"
    )
    assert plan["scope"] == traffic_math.SIGNAL_SCOPE_SOP2
    assert [a["segment_id"] for a in plan["adjustments"]] == ["RD_TPE_006"]
    assert plan["police_dispatch"] is None


def test_segment_name_is_used_for_cms_text():
    assert traffic_math.segment_name("RD_TPE_007") == "松高路"
    assert traffic_math.segment_name("RD_NOPE") == ""
