"""Unit tests for run-scoped immutable SnapshotBundle assembly."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from backend.incident_response import (
    MonitoringAlertOrigin,
    IncidentRecord,
    SnapshotService,
    SourceAvailability,
    UTC_PLUS_8,
    project_snapshot_trace,
    resolve_effective_event_time,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"


def local_time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 20, hour, minute, tzinfo=UTC_PLUS_8)


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


def copied_sources(tmp_path: Path) -> dict[str, Path]:
    names = {
        "traffic_path": "city_traffic_flow.csv",
        "crowd_path": "signaling_crowd_density.csv",
        "road_network_path": "road_network_geometry.json",
        "sop_path": "emergency_traffic_sop.txt",
    }
    paths: dict[str, Path] = {}
    for argument, filename in names.items():
        destination = tmp_path / filename
        shutil.copyfile(DATA_DIR / filename, destination)
        paths[argument] = destination
    return paths


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_first_run_snapshot_fixes_records_times_availability_and_versions(
    tmp_path: Path,
) -> None:
    paths = copied_sources(tmp_path)
    clock = {"now": local_time(21)}
    service = SnapshotService(**paths, clock_now=lambda: clock["now"])

    first = service.build_snapshot("run-1", effective_event_time=local_time(22, 15))
    fixed_json = first.model_dump_json()

    assert first.traffic.actual_data_time == local_time(22, 15)
    assert first.crowd.actual_data_time == local_time(22, 15)
    assert first.traffic.availability is SourceAvailability.AVAILABLE
    assert first.crowd.availability is SourceAvailability.AVAILABLE
    assert first.road_network.availability is SourceAvailability.AVAILABLE
    assert first.sop.availability is SourceAvailability.AVAILABLE
    assert first.traffic.content_hash == sha256(paths["traffic_path"])
    assert first.crowd.content_hash == sha256(paths["crowd_path"])
    assert first.road_network.content_hash == sha256(paths["road_network_path"])
    assert first.sop.content_hash == sha256(paths["sop_path"])
    assert first.traffic.schema_version == "1.0"
    assert first.sop.schema_version == "1.0"
    assert first.sop.records[0]["content"].strip()

    with pytest.raises(TypeError):
        first.traffic.records[0]["segment_id"] = "changed"

    paths["traffic_path"].write_text("invalid", encoding="utf-8")
    paths["crowd_path"].write_text("invalid", encoding="utf-8")
    paths["road_network_path"].write_text("[]", encoding="utf-8")
    paths["sop_path"].write_text("changed SOP", encoding="utf-8")
    clock["now"] = local_time(23)

    repeated = service.build_snapshot(
        "run-1",
        effective_event_time=local_time(23),
        simulation_clock_time=local_time(23),
    )

    assert repeated is first
    assert repeated.model_dump_json() == fixed_json
    assert repeated.simulation_clock_time == local_time(21)
    assert repeated.effective_event_time == local_time(22, 15)


def test_unavailable_sources_keep_reasons_and_trace_projection(tmp_path: Path) -> None:
    paths = copied_sources(tmp_path)
    paths["road_network_path"].unlink()
    paths["sop_path"].unlink()
    service = SnapshotService(**paths)

    bundle = service.build_snapshot(
        "run-unavailable",
        effective_event_time="2026-05-20 16:59",
        simulation_clock_time=local_time(17),
    )
    projection = project_snapshot_trace(bundle)
    evidence = {item.source: item for item in projection.source_availability}
    actual_times = dict(projection.times.source_actual_times)

    assert bundle.traffic.availability is SourceAvailability.UNAVAILABLE
    assert bundle.crowd.availability is SourceAvailability.UNAVAILABLE
    assert bundle.road_network.availability is SourceAvailability.UNAVAILABLE
    assert bundle.sop.availability is SourceAvailability.UNAVAILABLE
    assert "no complete time slice" in evidence["traffic"].reason
    assert evidence["road_network"].reason
    assert evidence["sop"].reason
    assert actual_times == {
        "traffic": None,
        "crowd": None,
        "road_network": None,
        "sop": None,
    }
    assert projection.times.effective_event_time == local_time(16, 59)
    assert projection.times.simulation_clock_time == local_time(17)
    assert projection.event_time_preview_sources == ()


def test_effective_event_time_uses_alert_data_time_only_for_promotion() -> None:
    incident = make_record(timestamp="2026-05-20 22:15")
    origin = MonitoringAlertOrigin(
        monitoring_alert_id="alert-1",
        data_time=local_time(21, 30),
        threshold=0.85,
        previous_value=0.84,
        current_value=0.86,
    )

    assert resolve_effective_event_time(
        incident, source_label="json_upload"
    ) == local_time(22, 15)
    assert resolve_effective_event_time(
        incident, source_label="json_upload"
    ) == local_time(22, 15)
    assert resolve_effective_event_time(
        incident,
        source_label="monitoring_promotion",
        monitoring_origin=origin,
    ) == local_time(21, 30)
    with pytest.raises(ValueError, match="Monitoring Alert data time"):
        resolve_effective_event_time(
            incident,
            source_label="monitoring_promotion",
        )


def test_future_event_snapshot_uses_event_as_of_without_mutating_clock(
    tmp_path: Path,
) -> None:
    paths = copied_sources(tmp_path)

    class FakeClock:
        def __init__(self) -> None:
            self.current = local_time(17)
            self.calls = 0

        def now(self) -> datetime:
            self.calls += 1
            return self.current

    clock = FakeClock()
    service = SnapshotService(**paths, clock_now=clock.now)

    bundle = service.build_snapshot(
        "run-future", effective_event_time=local_time(22, 15)
    )
    projection = project_snapshot_trace(bundle)

    assert clock.current == local_time(17)
    assert clock.calls == 1
    assert bundle.simulation_clock_time == local_time(17)
    assert bundle.traffic.requested_as_of == local_time(22, 15)
    assert bundle.crowd.requested_as_of == local_time(22, 15)
    assert projection.event_time_preview_sources == ("traffic", "crowd")
    assert service.get_snapshot("run-future") is bundle
