"""The uploaded live_incidents.json format is the only injection source.

These tests pin the real field shape supplied by the operator, including the
optional ``affected_road`` reference that crowd events carry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.incident_response import (
    EventCategory,
    IncidentPayloadParser,
    IncidentPayloadValidationError,
    IncidentReferenceCatalog,
    load_repository_sources,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
LIVE_INCIDENTS = DATA_DIR / "live_incidents.json"


@pytest.fixture
def parser() -> IncidentPayloadParser:
    sources = load_repository_sources(
        traffic_path=DATA_DIR / "city_traffic_flow.csv",
        crowd_path=DATA_DIR / "signaling_crowd_density.csv",
        road_network_path=DATA_DIR / "road_network_geometry.json",
    )
    return IncidentPayloadParser(
        IncidentReferenceCatalog(
            road_segment_ids=(r.segment_id for r in sources.road_network.records),
            crowd_station_ids=sources.crowd.known_ids,
        )
    )


def test_real_live_incidents_file_parses_and_classifies_all_three_categories(
    parser: IncidentPayloadParser,
) -> None:
    payload = parser.parse(LIVE_INCIDENTS.read_bytes())

    assert [r.event_id for r in payload.incidents] == [
        "TPE_2026_ACC_001",
        "TPE_2026_EVT_002",
        "TPE_2026_EVT_003",
    ]
    assert [r.original_index for r in payload.incidents] == [0, 1, 2]
    assert [r.category for r in payload.incidents] == [
        EventCategory.ROAD_DISRUPTION,
        EventCategory.CROWD_SURGE,
        EventCategory.SIGNAL_FAILURE,
    ]
    # The crowd event carries a secondary road reference; the others do not.
    assert payload.incidents[1].affected_road == "RD_TPE_001"
    assert payload.incidents[0].affected_road is None
    assert payload.incidents[2].affected_road is None


def test_upload_and_direct_json_entry_points_agree_on_the_real_file(
    parser: IncidentPayloadParser,
) -> None:
    content = LIVE_INCIDENTS.read_bytes()

    assert parser.parse_upload(filename="live_incidents.json", content=content) == parser.parse(
        content
    )


def test_affected_road_must_reference_a_known_segment(
    parser: IncidentPayloadParser,
) -> None:
    events = json.loads(LIVE_INCIDENTS.read_text(encoding="utf-8"))
    events[1]["affected_road"] = "RD_DOES_NOT_EXIST"

    with pytest.raises(IncidentPayloadValidationError) as caught:
        parser.validate(events)

    assert ("incidents[1].affected_road", "road_segment_unknown") in {
        (d.path, d.code) for d in caught.value.details
    }


def test_signal_failure_keeps_its_category_despite_a_road_segment(
    parser: IncidentPayloadParser,
) -> None:
    """A Power_Failure on an RD_ segment must classify as Signal_Failure, not Road."""

    events = json.loads(LIVE_INCIDENTS.read_text(encoding="utf-8"))
    payload = parser.validate(events)

    signal = payload.incidents[2]
    assert signal.affected_segment.startswith("RD_")
    assert signal.category is EventCategory.SIGNAL_FAILURE
    # Road_Disruption status rules must not be applied to signal events.
    assert signal.status == "Caution"
