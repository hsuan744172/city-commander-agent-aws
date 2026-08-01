"""Unit tests for strict, immutable incident response domain contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.incident_response import (
    ApiError,
    ApiErrorDetail,
    ApiErrorResponse,
    CmsMessage,
    CmsMessageSet,
    DecisionTrace,
    DeterministicResult,
    EteResult,
    IncidentPayload,
    IncidentPreview,
    IncidentRecord,
    IncidentRun,
    MonitoringAlert,
    PreviewEventSummary,
    PublicationRecord,
    RequiredResultCheck,
    RunProgress,
    RunStatus,
    SnapshotBundle,
    SourceAvailabilityEvidence,
    StaticSourceSnapshot,
    TIMEZONE_LABEL,
    TraceTimes,
    UTC_PLUS_8,
    UntypedSourceSnapshot,
    ValidationSummary,
    parse_utc8_datetime,
    project_utc8_datetime,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
LOCAL_TIME = datetime(2026, 5, 20, 22, 15, tzinfo=UTC_PLUS_8)


def make_record(**changes: object) -> IncidentRecord:
    values: dict[str, object] = {
        "event_id": "event-1",
        "type": "Road_Collapse",
        "location": "忠孝東路四段",
        "affected_segment": "RD_TPE_002",
        "severity": "High",
        "description": "道路阻斷",
        "timestamp": "2026-05-20 22:15",
        "status": "Blocked",
        "category": "Road_Disruption",
        "original_index": 0,
    }
    values.update(changes)
    return IncidentRecord(**values)


def make_payload() -> IncidentPayload:
    return IncidentPayload(incidents=(make_record(),), normalized_hash=HASH_A)


def make_dynamic_snapshot(source: str) -> UntypedSourceSnapshot:
    return UntypedSourceSnapshot(
        source=source,
        schema_version="1.0",
        content_hash=HASH_A,
        requested_as_of=LOCAL_TIME,
        actual_data_time=LOCAL_TIME,
        availability="available",
        records=({"id": "one", "nested": [1, 2]},),
        validation_summary=ValidationSummary(valid=True, record_count=1),
    )


def make_static_snapshot(source: str) -> StaticSourceSnapshot:
    return StaticSourceSnapshot(
        source=source,
        schema_version="1.0",
        content_hash=HASH_B,
        requested_as_of=LOCAL_TIME,
        availability="available",
        records=({"id": "one"},),
        validation_summary=ValidationSummary(valid=True, record_count=1),
    )


def make_snapshot_bundle() -> SnapshotBundle:
    return SnapshotBundle(
        effective_event_time=LOCAL_TIME,
        simulation_clock_time=LOCAL_TIME,
        traffic=make_dynamic_snapshot("traffic"),
        crowd=make_dynamic_snapshot("crowd"),
        road_network=make_static_snapshot("road_network"),
        sop=make_static_snapshot("sop"),
    )


def make_cms_message() -> CmsMessage:
    text = "請避開事故路段"
    return CmsMessage(language="zh-TW", text=text, char_count=len(text), facts_valid=True)


def make_cms_set() -> CmsMessageSet:
    return CmsMessageSet(
        status="publishable",
        multilingual_triggered=False,
        sop6_status="not_triggered",
        messages=(make_cms_message(),),
    )


def make_ete() -> EteResult:
    return EteResult(
        status="calculated",
        affected_segments=("RD_TPE_002",),
        saturation_values=(0.75,),
        arithmetic_mean=0.75,
        severity="High",
        base_clearance_minutes=40.0,
        congestion_penalty_minutes=15.0,
        total_minutes=55.0,
    )


def make_result() -> DeterministicResult:
    return DeterministicResult(
        result_schema_version="1.0",
        event_id="event-1",
        category="Road_Disruption",
        effective_event_time=LOCAL_TIME,
        input_versions=(),
        sop_decisions=(),
        route_plan=None,
        ete=make_ete(),
        cms_message_set=make_cms_set(),
        required_result_check=RequiredResultCheck(complete=True),
    )


def make_trace() -> DecisionTrace:
    return DecisionTrace(
        trace_schema_version="1.0",
        event_id="event-1",
        times=TraceTimes(
            effective_event_time=LOCAL_TIME,
            simulation_clock_time=LOCAL_TIME,
            source_actual_times=(("traffic", LOCAL_TIME),),
        ),
        normalized_input_subset={"event_id": "event-1"},
        source_availability=(
            SourceAvailabilityEvidence(
                source="traffic", availability="available", actual_data_time=LOCAL_TIME
            ),
        ),
        rules=(),
        ete_calculation=make_ete(),
    )


def test_incident_record_trims_required_strings_and_parses_utc8_time() -> None:
    record = make_record(
        event_id="  event-1  ",
        location="  忠孝東路四段  ",
        description="  道路阻斷  ",
    )

    assert record.event_id == "event-1"
    assert record.location == "忠孝東路四段"
    assert record.description == "道路阻斷"
    assert record.effective_event_time == LOCAL_TIME


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", "   "),
        ("type", "x" * 65),
        ("location", "x" * 121),
        ("affected_segment", 123),
        ("description", "x" * 501),
        ("severity", "Low"),
        ("severity", 1),
        ("timestamp", datetime(2026, 5, 20, 22, 15)),
    ],
)
def test_incident_record_rejects_invalid_boundaries_and_wrong_types(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        make_record(**{field: value})


@pytest.mark.parametrize(
    "value",
    [
        "2026-5-20 22:15",
        "2026-05-20T22:15",
        "2026-02-29 22:15",
        "2026-05-20 24:00",
        " 2026-05-20 22:15",
    ],
)
def test_incident_timestamp_rejects_non_contract_or_impossible_dates(value: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        make_record(timestamp=value)


def test_incident_timestamp_accepts_real_leap_day() -> None:
    assert parse_utc8_datetime("2024-02-29 00:00") == datetime(
        2024, 2, 29, tzinfo=UTC_PLUS_8
    )


def test_payload_is_strict_and_immutable() -> None:
    payload = make_payload()

    with pytest.raises(ValidationError):
        IncidentPayload(incidents=[make_record()], normalized_hash=HASH_A)
    with pytest.raises(ValidationError):
        payload.normalized_hash = HASH_B
    with pytest.raises(ValidationError):
        IncidentPayload(incidents=(make_record(),), normalized_hash=HASH_A, unknown=True)


def test_time_projection_converts_same_instant_to_utc8_and_json_contract() -> None:
    utc_time = datetime(2026, 5, 20, 14, 15, tzinfo=timezone.utc)
    preview = IncidentPreview(
        preview_id="preview-1",
        preview_hash=HASH_A,
        source_label="json_upload",
        normalized_payload=make_payload(),
        event_summaries=(
            PreviewEventSummary(
                original_index=0,
                event_id="event-1",
                category="Road_Disruption",
                location="忠孝東路四段",
                affected_segment="RD_TPE_002",
                severity="High",
                timestamp="2026-05-20 22:15",
                possible_sop_articles=(2,),
            ),
        ),
        created_at=utc_time,
        expires_at=utc_time + timedelta(minutes=5),
        simulation_clock_time=utc_time,
        contains_future_event=False,
        required_confirmations=("payload",),
    )

    assert project_utc8_datetime(utc_time) == "2026-05-20 22:15"
    assert preview.model_dump(mode="json")["created_at"] == "2026-05-20 22:15"
    with pytest.raises(ValueError):
        project_utc8_datetime(datetime(2026, 5, 20, 22, 15))


def test_snapshot_records_are_deeply_immutable_and_do_not_use_future_data() -> None:
    snapshot = make_dynamic_snapshot("traffic")

    with pytest.raises(TypeError):
        snapshot.records[0]["id"] = "changed"
    assert snapshot.records[0]["nested"] == (1, 2)
    assert snapshot.model_dump(mode="json")["records"][0]["nested"] == [1, 2]

    with pytest.raises(ValidationError):
        UntypedSourceSnapshot(
            source="traffic",
            schema_version="1.0",
            content_hash=HASH_A,
            requested_as_of=LOCAL_TIME,
            actual_data_time=LOCAL_TIME + timedelta(minutes=1),
            availability="available",
            records=(),
            validation_summary=ValidationSummary(valid=True, record_count=0),
        )


def test_core_result_trace_run_and_monitoring_contracts_construct() -> None:
    result = make_result()
    trace = make_trace()
    run = IncidentRun(
        run_id="run-1",
        demo_session_id="session-1",
        source_label="json_upload",
        status="accepted",
        accepted_at=LOCAL_TIME,
        accepted_monotonic=1.0,
        payload_hash=HASH_A,
        normalized_payload=make_payload(),
        idempotency_key_hash=HASH_B,
        simulation_clock_at_accept=LOCAL_TIME,
        progress=RunProgress(completed_count=0, total_count=1),
        snapshot_bundle=make_snapshot_bundle(),
    )
    alert = MonitoringAlert(
        alert_id="alert-1",
        segment_id="RD_TPE_002",
        metric="Saturation_Score",
        threshold=0.85,
        level="B",
        previous_value=0.84,
        current_value=0.85,
        data_time=LOCAL_TIME,
        created_at=LOCAL_TIME,
    )

    assert result.required_result_check.complete is True
    assert trace.normalized_input_subset["event_id"] == "event-1"
    assert run.status is RunStatus.ACCEPTED
    assert run.status.is_terminal is False
    assert alert.source_label.value == "time_series_alert"


def test_decision_trace_rejects_private_reasoning_fields() -> None:
    values = make_trace().model_dump()
    values["normalized_input_subset"] = {"chain_of_thought": "private"}

    with pytest.raises(ValidationError):
        DecisionTrace.model_validate(values)


def test_cms_publication_is_atomic_shaped_and_utc8_projected() -> None:
    message = make_cms_message()
    publication = PublicationRecord(
        publication_id="publication-1",
        run_id="run-1",
        message_set_hash=HASH_A,
        languages=("zh-TW",),
        messages=(message,),
        published_at=LOCAL_TIME,
    )

    projected = publication.model_dump(mode="json")
    assert projected["published_at"] == "2026-05-20 22:15"
    assert projected["channel_notice"] == "Simulated_Publish－未連接真實通路"
    with pytest.raises(ValidationError):
        PublicationRecord(
            publication_id="publication-1",
            run_id="run-1",
            message_set_hash=HASH_A,
            languages=("en",),
            messages=(message,),
            published_at=LOCAL_TIME,
        )


def test_api_errors_have_version_timezone_paths_and_safe_internal_factory() -> None:
    public = ApiErrorResponse(
        error=ApiError(
            code="INCIDENT_FIELD_INVALID",
            message="事件欄位驗證失敗",
            trace_id="trace-1",
            details=(
                ApiErrorDetail(
                    path="incidents[0].severity",
                    code="enum",
                    message="僅接受 Critical、High、Medium",
                ),
            ),
        )
    )
    internal = ApiErrorResponse.internal(code="INCIDENT_INTERNAL", trace_id="trace-2")

    assert public.contract_version == "1.0"
    assert public.timezone == TIMEZONE_LABEL
    assert public.error.details[0].path == "incidents[0].severity"
    serialized = internal.model_dump_json()
    assert "trace-2" in serialized
    assert "stack" not in serialized.casefold()
    assert "vendor" not in serialized.casefold()
    assert internal.error.details == ()
