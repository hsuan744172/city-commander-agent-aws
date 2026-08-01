"""Unit tests for source validation and strict as-of selection."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from backend.incident_response import (
    UTC_PLUS_8,
    common_complete_timeline,
    load_crowd_source,
    load_repository_sources,
    load_road_network,
    load_traffic_source,
    select_strict_as_of,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"

TRAFFIC_HEADER = (
    "Timestamp,Segment_ID,Road_Name,Avg_Speed,Vehicle_Count,"
    "Saturation_Score,Lane_Status\n"
)
CROWD_HEADER = (
    "Timestamp,BS_ID,Location_Name,User_Count,Stay_Time_Avg,"
    "Growth_Rate,Roaming_User_Pct\n"
)


def local_time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 20, hour, minute, tzinfo=UTC_PLUS_8)


def test_repository_sources_validate_and_share_only_complete_times() -> None:
    sources = load_repository_sources(
        traffic_path=DATA_DIR / "city_traffic_flow.csv",
        crowd_path=DATA_DIR / "signaling_crowd_density.csv",
        road_network_path=DATA_DIR / "road_network_geometry.json",
    )

    assert sources.traffic.source_errors == ()
    assert sources.crowd.source_errors == ()
    assert sources.road_network.valid is True
    assert len(sources.road_network.records) == 15
    assert local_time(22, 15) in sources.common_complete_timeline
    assert sources.common_complete_timeline == common_complete_timeline(
        sources.traffic, sources.crowd
    )
    assert set(sources.common_complete_timeline) <= set(sources.traffic.complete_times)
    assert set(sources.common_complete_timeline) <= set(sources.crowd.complete_times)


def test_each_source_selects_latest_complete_slice_independently() -> None:
    traffic = load_traffic_source(DATA_DIR / "city_traffic_flow.csv")
    crowd = load_crowd_source(DATA_DIR / "signaling_crowd_density.csv")

    traffic_exact = select_strict_as_of(traffic, "2026-05-20 22:15")
    traffic_between = select_strict_as_of(traffic, "2026-05-20 22:14")
    crowd_between = select_strict_as_of(crowd, "2026-05-20 22:14")

    assert traffic_exact.available is True
    assert traffic_exact.actual_data_time == local_time(22, 15)
    assert len(traffic_exact.records) == 15
    assert traffic_between.actual_data_time == local_time(22, 10)
    assert tuple(record.segment_id for record in traffic_between.records) == ("RD_TPE_002",)
    assert crowd_between.actual_data_time == local_time(22, 0)
    assert all(record.timestamp <= crowd_between.requested_as_of for record in crowd_between.records)


def test_as_of_never_falls_forward_to_future_first_slice() -> None:
    traffic = load_traffic_source(DATA_DIR / "city_traffic_flow.csv")

    selection = select_strict_as_of(traffic, "2026-05-20 16:59")

    assert selection.available is False
    assert selection.actual_data_time is None
    assert selection.records == ()
    assert "no complete time slice" in selection.unavailable_reason


def test_invalid_or_duplicate_rows_invalidate_only_their_slice(tmp_path: Path) -> None:
    traffic_path = tmp_path / "traffic.csv"
    traffic_path.write_text(
        TRAFFIC_HEADER
        + "2026-05-20 20:00,RD_1,道路一,30,100,0.5,Normal\n"
        + "2026-05-20 21:00,RD_2,道路二,fast,100,0.6,Normal\n"
        + "2026-05-20 22:00,RD_3,道路三,20,200,0.8,Congested\n"
        + "2026-05-20 22:00,RD_3,道路三,19,210,0.9,Congested\n",
        encoding="utf-8",
    )

    source = load_traffic_source(traffic_path)
    selection = select_strict_as_of(source, "2026-05-20 22:30")

    assert tuple(time_slice.complete for time_slice in source.slices) == (True, False, False)
    assert "required number" in source.slices[1].errors[0]
    assert "duplicate identifier RD_3" in source.slices[2].errors[0]
    assert selection.available is True
    assert selection.actual_data_time == local_time(20)
    assert tuple(record.segment_id for record in selection.records) == ("RD_1",)


def test_crowd_loader_validates_fields_and_normalizes_percentages(tmp_path: Path) -> None:
    crowd_path = tmp_path / "crowd.csv"
    crowd_path.write_text(
        CROWD_HEADER
        + "2026-05-20 20:00,BS_1,站點一,100,15,0.2,45%\n"
        + "2026-05-20 21:00,BS_2,站點二,not-an-int,15,0.3,0.2\n",
        encoding="utf-8",
    )

    source = load_crowd_source(crowd_path)
    selected = select_strict_as_of(source, local_time(21))

    assert source.slices[0].complete is True
    assert source.slices[0].records[0].roaming_user_pct == 0.45
    assert source.slices[1].complete is False
    assert selected.actual_data_time == local_time(20)


def test_missing_csv_columns_produce_no_complete_slice(tmp_path: Path) -> None:
    traffic_path = tmp_path / "traffic.csv"
    traffic_path.write_text("Timestamp,Segment_ID\n2026-05-20 20:00,RD_1\n", encoding="utf-8")

    source = load_traffic_source(traffic_path)
    selected = select_strict_as_of(source, local_time(20))

    assert source.complete_times == ()
    assert "missing required columns" in source.source_errors[0]
    assert selected.available is False


def test_road_network_rejects_dangling_and_invalid_structural_references(
    tmp_path: Path,
) -> None:
    road_path = tmp_path / "roads.json"
    road_path.write_text(
        json.dumps(
            [
                {
                    "segment_id": "RD_1",
                    "name": "道路一",
                    "flow_direction": "東向",
                    "intersections": ["道路二"],
                    "capacity_vph": 1000,
                    "alternatives": ["RD_MISSING"],
                    "nearby_stations": ["BS_MISSING"],
                },
                {
                    "segment_id": "RD_2",
                    "name": "道路二",
                    "flow_direction": "西向",
                    "intersections": [],
                    "capacity_vph": -1,
                    "alternatives": [],
                    "nearby_stations": [],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    network = load_road_network(road_path, known_station_ids={"BS_1"})

    assert network.valid is False
    assert any("unknown segment RD_MISSING" in error for error in network.errors)
    assert any("unknown station BS_MISSING" in error for error in network.errors)
    assert any("intersections: requires at least one entry" in error for error in network.errors)


def test_road_network_accepts_ordered_intersection_place_names(tmp_path: Path) -> None:
    road_path = tmp_path / "roads.json"
    road_path.write_text(
        json.dumps(
            [
                {
                    "segment_id": "RD_1",
                    "name": "道路一",
                    "flow_direction": "東向",
                    "intersections": ["未建模橋梁", "道路二"],
                    "capacity_vph": 1000,
                    "alternatives": ["RD_2"],
                    "nearby_stations": ["BS_1"],
                },
                {
                    "segment_id": "RD_2",
                    "name": "道路二",
                    "flow_direction": "西向",
                    "intersections": ["道路一"],
                    "capacity_vph": 900,
                    "alternatives": [],
                    "nearby_stations": [],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    network = load_road_network(road_path, known_station_ids={"BS_1"})

    assert network.valid is True
    assert network.records[0].intersections == ("未建模橋梁", "道路二")
