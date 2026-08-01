"""Focused unit tests for Task 1.3 shared payload parsing and validation."""

from __future__ import annotations

import json

import pytest

from backend.incident_response import (
    MAX_UPLOAD_BYTES,
    EventCategory,
    IncidentPayloadParser,
    IncidentPayloadValidationError,
    IncidentReferenceCatalog,
    canonical_json_bytes,
    canonical_sha256,
)


def make_event(event_id: str, **changes: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_id": event_id,
        "type": "Road_Collapse",
        "location": "忠孝東路四段",
        "affected_segment": "RD_TPE_002",
        "severity": "High",
        "description": "道路阻斷",
        "timestamp": "2026-05-20 22:15",
        "status": "Blocked",
    }
    event.update(changes)
    return event


@pytest.fixture
def parser() -> IncidentPayloadParser:
    return IncidentPayloadParser(
        IncidentReferenceCatalog(
            road_segment_ids={"RD_TPE_002", "RD_TPE_013"},
            crowd_station_ids={"BS_MRT_BL17"},
        )
    )


def test_direct_array_and_upload_wrapper_share_normalization_and_preserve_order(
    parser: IncidentPayloadParser,
) -> None:
    road = make_event(" road-1 ")
    crowd = make_event(
        "crowd-1",
        type="Crowd_Gathering",
        affected_segment="BS_MRT_BL17",
        description="人群聚集",
        status=" Observing ",
    )
    signal = make_event(
        "signal-1",
        type="Power_Failure",
        affected_segment="RD_TPE_013",
        severity="Medium",
        description="供電中斷",
        status=None,
    )

    direct = parser.validate([road, crowd, signal])
    upload = parser.parse_upload(
        filename="incidents.JSON",
        content=json.dumps(
            {"incidents": [road, crowd, signal]}, ensure_ascii=False
        ).encode("utf-8"),
    )

    assert [record.event_id for record in direct.incidents] == [
        "road-1",
        "crowd-1",
        "signal-1",
    ]
    assert [record.original_index for record in direct.incidents] == [0, 1, 2]
    assert [record.category for record in direct.incidents] == [
        EventCategory.ROAD_DISRUPTION,
        EventCategory.CROWD_SURGE,
        EventCategory.SIGNAL_FAILURE,
    ]
    assert direct.incidents[1].status == "Observing"
    assert upload == direct


def test_parser_aggregates_field_category_reference_status_and_duplicate_errors(
    parser: IncidentPayloadParser,
) -> None:
    invalid_road = make_event(
        "same-id",
        affected_segment="RD_UNKNOWN",
        severity="Low",
        status="Open",
    )
    conflicting = make_event(
        "same-id",
        type="Power_Failure",
        affected_segment="BS_MRT_BL17",
        description="號誌故障",
        status=None,
    )

    with pytest.raises(IncidentPayloadValidationError) as caught:
        parser.validate([invalid_road, conflicting])

    details = caught.value.details
    paths_and_codes = {(detail.path, detail.code) for detail in details}
    assert ("incidents[0].severity", "enum") in paths_and_codes
    assert ("incidents[0].affected_segment", "road_segment_unknown") in paths_and_codes
    assert ("incidents[0].status", "road_status_invalid") in paths_and_codes
    assert ("incidents[1].affected_segment", "category_conflict") in paths_and_codes
    assert ("incidents[1].type", "category_conflict") in paths_and_codes
    assert ("incidents[0].event_id", "duplicate_event_id") in paths_and_codes
    assert ("incidents[1].event_id", "duplicate_event_id") in paths_and_codes


def test_unclassified_event_reports_type_and_affected_segment_paths(
    parser: IncidentPayloadParser,
) -> None:
    event = make_event(
        "unknown",
        type="Weather",
        affected_segment="AREA_1",
        status=None,
    )

    with pytest.raises(IncidentPayloadValidationError) as caught:
        parser.validate([event])

    assert [(detail.path, detail.code) for detail in caught.value.details] == [
        ("incidents[0].type", "category_unclassified"),
        ("incidents[0].affected_segment", "category_unclassified"),
    ]


@pytest.mark.parametrize(
    ("value", "expected_code"),
    [
        ([], "INCIDENT_PAYLOAD_EMPTY"),
        ({"incidents": [], "other": []}, "INCIDENT_PAYLOAD_SHAPE_INVALID"),
        ({"incidents": "not-an-array"}, "INCIDENT_PAYLOAD_SHAPE_INVALID"),
        ("not-an-object", "INCIDENT_PAYLOAD_SHAPE_INVALID"),
    ],
)
def test_top_level_shape_errors_are_structured(
    parser: IncidentPayloadParser,
    value: object,
    expected_code: str,
) -> None:
    with pytest.raises(IncidentPayloadValidationError) as caught:
        parser.validate(value)

    assert caught.value.code == expected_code
    assert caught.value.details


def test_more_than_100_records_is_rejected_before_record_validation(
    parser: IncidentPayloadParser,
) -> None:
    with pytest.raises(IncidentPayloadValidationError) as caught:
        parser.validate([{} for _ in range(101)])

    assert caught.value.code == "INCIDENT_PAYLOAD_TOO_MANY_RECORDS"
    assert caught.value.details[0].path == "incidents"


def test_malformed_json_is_redacted_and_convertible_to_api_error(
    parser: IncidentPayloadParser,
) -> None:
    malformed = '{"incidents": [secret-token]}'

    with pytest.raises(IncidentPayloadValidationError) as caught:
        parser.parse(malformed)

    api_error = caught.value.as_api_error(trace_id="trace-1")
    serialized = api_error.model_dump_json()
    assert api_error.code == "INCIDENT_JSON_MALFORMED"
    assert api_error.details[0].path == "$"
    assert "secret-token" not in serialized
    assert "Traceback" not in serialized


def test_upload_enforces_extension_size_and_utf8_before_json(
    parser: IncidentPayloadParser,
) -> None:
    cases = [
        ("incidents.txt", b"{}", "INCIDENT_FILE_TYPE_INVALID"),
        ("incidents.json", b"", "INCIDENT_FILE_EMPTY"),
        (
            "incidents.json",
            b" " * (MAX_UPLOAD_BYTES + 1),
            "INCIDENT_FILE_TOO_LARGE",
        ),
        ("incidents.json", b"\xff", "INCIDENT_FILE_ENCODING_INVALID"),
    ]

    for filename, content, expected_code in cases:
        with pytest.raises(IncidentPayloadValidationError) as caught:
            parser.parse_upload(filename=filename, content=content)
        assert caught.value.code == expected_code


def test_canonical_json_sorts_object_keys_keeps_unicode_and_preserves_array_order() -> None:
    left = {"b": "台北", "a": [{"z": 2, "y": 1}, 3]}
    same = {"a": [{"y": 1, "z": 2}, 3], "b": "台北"}
    reordered = {"a": [3, {"y": 1, "z": 2}], "b": "台北"}

    assert canonical_json_bytes(left) == canonical_json_bytes(same)
    assert b"\\u" not in canonical_json_bytes(left)
    assert canonical_sha256(left) == canonical_sha256(same)
    assert canonical_sha256(left) != canonical_sha256(reordered)
