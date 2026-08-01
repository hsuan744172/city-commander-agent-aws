"""Run-scoped immutable snapshot assembly and Decision Trace evidence projection.

The source loaders validate data and perform strict as-of selection.  This service
owns the next consistency boundary: the first bundle created for a run is retained
and returned unchanged, regardless of later source-file, cache, or clock changes.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from .domain import (
    IncidentRecord,
    MonitoringAlertOrigin,
    SnapshotBundle,
    SourceAvailability,
    SourceAvailabilityEvidence,
    SourceLabel,
    StaticSourceSnapshot,
    TraceTimes,
    UTC_PLUS_8,
    UntypedSourceSnapshot,
    ValidationSummary,
    parse_utc8_datetime,
    project_utc8_datetime,
)
from .sources import (
    AsOfSelection,
    RepositorySources,
    load_repository_sources,
    select_strict_as_of,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
TRAFFIC_FILENAME: Final[str] = "city_traffic_flow.csv"
CROWD_FILENAME: Final[str] = "signaling_crowd_density.csv"
ROAD_NETWORK_FILENAME: Final[str] = "road_network_geometry.json"
SOP_FILENAME: Final[str] = "emergency_traffic_sop.txt"
DEFAULT_TRAFFIC_PATH: Final[Path] = PROJECT_ROOT / "data" / TRAFFIC_FILENAME
DEFAULT_CROWD_PATH: Final[Path] = PROJECT_ROOT / "data" / CROWD_FILENAME
DEFAULT_ROAD_NETWORK_PATH: Final[Path] = PROJECT_ROOT / "data" / ROAD_NETWORK_FILENAME
DEFAULT_SOP_PATH: Final[Path] = PROJECT_ROOT / "data" / SOP_FILENAME
SOP_SOURCE: Final[str] = "sop"
SOP_SCHEMA_VERSION: Final[str] = "1.0"
_EMPTY_CONTENT_HASH: Final[str] = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotTraceProjection:
    """Snapshot-owned fields that Task 3 can place directly in DecisionTrace."""

    times: TraceTimes
    source_availability: tuple[SourceAvailabilityEvidence, ...]
    event_time_preview_sources: tuple[str, ...]


def _resolve_source(explicit: str | Path | None, filename: str) -> Path:
    """Pin an explicit path, or resolve S3-first with a local ``data/`` fallback."""

    if explicit is not None:
        return Path(explicit)
    try:
        from backend.data_source import get_data_path

        return get_data_path(filename)
    except Exception:  # pragma: no cover - the packaged data must still work
        return PROJECT_ROOT / "data" / filename


def _normalize_time(value: datetime | str, *, field: str) -> datetime:
    if isinstance(value, str):
        return parse_utc8_datetime(value)
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime or YYYY-MM-DD HH:MM string")
    # SimulationClock currently exposes local, offsetless pandas timestamps from
    # the repository data. Their contract timezone is explicitly UTC+8.
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC_PLUS_8)
    return value.astimezone(UTC_PLUS_8)


def _safe_reason(reason: str) -> str:
    normalized = reason.strip() or "source unavailable"
    return normalized[:500]


def _read_bytes(path: Path) -> tuple[bytes | None, str, str | None]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        return None, _EMPTY_CONTENT_HASH, f"cannot read source ({type(exc).__name__})"
    return content, hashlib.sha256(content).hexdigest(), None


def _freeze_record_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return project_utc8_datetime(value)
    if isinstance(value, dict):
        return {str(key): _freeze_record_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze_record_value(item) for item in value)
    return value


def _record_mapping(record: Any) -> dict[str, Any]:
    if is_dataclass(record) and not isinstance(record, type):
        return _freeze_record_value(asdict(record))
    if isinstance(record, dict):
        return _freeze_record_value(record)
    raise TypeError(f"unsupported source record type: {type(record).__name__}")


def _dynamic_snapshot(
    selection: AsOfSelection[Any],
    *,
    schema_version: str,
    content_hash: str,
) -> UntypedSourceSnapshot:
    if selection.available:
        records = tuple(_record_mapping(record) for record in selection.records)
        return UntypedSourceSnapshot(
            source=selection.source,
            schema_version=schema_version,
            content_hash=content_hash,
            requested_as_of=selection.requested_as_of,
            actual_data_time=selection.actual_data_time,
            availability=SourceAvailability.AVAILABLE,
            records=records,
            validation_summary=ValidationSummary(
                valid=True,
                record_count=len(records),
            ),
        )

    reason = _safe_reason(selection.unavailable_reason or f"{selection.source}: unavailable")
    return UntypedSourceSnapshot(
        source=selection.source,
        schema_version=schema_version,
        content_hash=content_hash,
        requested_as_of=selection.requested_as_of,
        availability=SourceAvailability.UNAVAILABLE,
        unavailable_reason=reason,
        records=(),
        validation_summary=ValidationSummary(
            valid=False,
            record_count=0,
            errors=(reason,),
        ),
    )


def _road_snapshot(
    sources: RepositorySources,
    *,
    requested_as_of: datetime,
    content_hash: str,
) -> StaticSourceSnapshot:
    road = sources.road_network
    if road.valid:
        records = tuple(_record_mapping(record) for record in road.records)
        return StaticSourceSnapshot(
            source=road.source,
            schema_version=road.schema_version,
            content_hash=content_hash,
            requested_as_of=requested_as_of,
            availability=SourceAvailability.AVAILABLE,
            records=records,
            validation_summary=ValidationSummary(
                valid=True,
                record_count=len(records),
            ),
        )

    reason = _safe_reason("; ".join(road.errors) or "road_network: unavailable")
    return StaticSourceSnapshot(
        source=road.source,
        schema_version=road.schema_version,
        content_hash=content_hash,
        requested_as_of=requested_as_of,
        availability=SourceAvailability.UNAVAILABLE,
        unavailable_reason=reason,
        records=(),
        validation_summary=ValidationSummary(
            valid=False,
            record_count=0,
            errors=tuple(_safe_reason(error) for error in road.errors) or (reason,),
        ),
    )


def _sop_snapshot(
    path: Path,
    *,
    requested_as_of: datetime,
) -> StaticSourceSnapshot:
    content, content_hash, read_error = _read_bytes(path)
    text: str | None = None
    reason = read_error
    if content is not None:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            reason = "source must be valid UTF-8 text"
        else:
            if not text.strip():
                reason = "source must contain at least one SOP rule"

    if reason is None and text is not None:
        return StaticSourceSnapshot(
            source=SOP_SOURCE,
            schema_version=SOP_SCHEMA_VERSION,
            content_hash=content_hash,
            requested_as_of=requested_as_of,
            availability=SourceAvailability.AVAILABLE,
            records=({"content": text},),
            validation_summary=ValidationSummary(valid=True, record_count=1),
        )

    unavailable_reason = _safe_reason(f"sop: {reason or 'unavailable'}")
    return StaticSourceSnapshot(
        source=SOP_SOURCE,
        schema_version=SOP_SCHEMA_VERSION,
        content_hash=content_hash,
        requested_as_of=requested_as_of,
        availability=SourceAvailability.UNAVAILABLE,
        unavailable_reason=unavailable_reason,
        records=(),
        validation_summary=ValidationSummary(
            valid=False,
            record_count=0,
            errors=(unavailable_reason,),
        ),
    )


def resolve_effective_event_time(
    incident: IncidentRecord,
    *,
    source_label: SourceLabel | str,
    monitoring_origin: MonitoringAlertOrigin | None = None,
) -> datetime:
    """Resolve the authoritative event time for injected and promoted events."""

    source = source_label if isinstance(source_label, SourceLabel) else SourceLabel(source_label)
    if source is SourceLabel.MONITORING_PROMOTION:
        if monitoring_origin is None:
            raise ValueError("monitoring_promotion requires Monitoring Alert data time")
        return monitoring_origin.data_time
    return incident.effective_event_time


def project_snapshot_trace(bundle: SnapshotBundle) -> SnapshotTraceProjection:
    """Project fixed bundle time/availability evidence for a Decision Trace.

    A dynamic source is marked as event-time preview data only when its actual
    data time is later than the frozen Simulation Clock and no later than the
    Effective Event Time.
    """

    snapshots = (bundle.traffic, bundle.crowd, bundle.road_network, bundle.sop)
    actual_times = tuple((snapshot.source, snapshot.actual_data_time) for snapshot in snapshots)
    evidence = tuple(
        SourceAvailabilityEvidence(
            source=snapshot.source,
            availability=snapshot.availability,
            actual_data_time=snapshot.actual_data_time,
            reason=snapshot.unavailable_reason,
        )
        for snapshot in snapshots
    )
    preview_sources = tuple(
        snapshot.source
        for snapshot in (bundle.traffic, bundle.crowd)
        if snapshot.actual_data_time is not None
        and bundle.simulation_clock_time < snapshot.actual_data_time <= bundle.effective_event_time
    )
    return SnapshotTraceProjection(
        times=TraceTimes(
            effective_event_time=bundle.effective_event_time,
            simulation_clock_time=bundle.simulation_clock_time,
            source_actual_times=actual_times,
        ),
        source_availability=evidence,
        event_time_preview_sources=preview_sources,
    )


class SnapshotService:
    """Thread-safe first-write-wins store of run-scoped SnapshotBundle values."""

    def __init__(
        self,
        *,
        traffic_path: str | Path | None = None,
        crowd_path: str | Path | None = None,
        road_network_path: str | Path | None = None,
        sop_path: str | Path | None = None,
        clock_now: Callable[[], datetime] | None = None,
        source_loader: Callable[[], RepositorySources] | None = None,
    ) -> None:
        # An explicit path pins that source. Otherwise the source is resolved per
        # snapshot through data_source, which prefers S3 and falls back to data/.
        self._traffic_path = _resolve_source(traffic_path, TRAFFIC_FILENAME)
        self._crowd_path = _resolve_source(crowd_path, CROWD_FILENAME)
        self._road_network_path = _resolve_source(road_network_path, ROAD_NETWORK_FILENAME)
        self._sop_path = _resolve_source(sop_path, SOP_FILENAME)
        self._clock_now = clock_now
        self._source_loader = source_loader or self._load_sources
        self._bundles: dict[str, SnapshotBundle] = {}
        self._lock = threading.RLock()

    def _load_sources(self) -> RepositorySources:
        return load_repository_sources(
            traffic_path=self._traffic_path,
            crowd_path=self._crowd_path,
            road_network_path=self._road_network_path,
        )

    def get_snapshot(self, run_id: str) -> SnapshotBundle | None:
        normalized_run_id = str(run_id).strip()
        if not normalized_run_id:
            raise ValueError("run_id must not be empty")
        with self._lock:
            return self._bundles.get(normalized_run_id)

    def build_snapshot(
        self,
        run_id: str,
        *,
        effective_event_time: datetime | str,
        simulation_clock_time: datetime | str | None = None,
    ) -> SnapshotBundle:
        """Return a run's fixed first snapshot, building it exactly once."""

        normalized_run_id = str(run_id).strip()
        if not normalized_run_id:
            raise ValueError("run_id must not be empty")
        if len(normalized_run_id) > 64:
            raise ValueError("run_id must contain at most 64 characters")

        with self._lock:
            existing = self._bundles.get(normalized_run_id)
            if existing is not None:
                return existing

            effective_time = _normalize_time(
                effective_event_time, field="effective_event_time"
            )
            if simulation_clock_time is None:
                if self._clock_now is None:
                    raise ValueError(
                        "simulation_clock_time is required when clock_now is not configured"
                    )
                simulation_clock_time = self._clock_now()
            clock_time = _normalize_time(
                simulation_clock_time, field="simulation_clock_time"
            )

            # Capture hashes and validated records during the same first-build
            # critical section. Later calls never touch paths, caches, or clock.
            _, traffic_hash, _ = _read_bytes(self._traffic_path)
            _, crowd_hash, _ = _read_bytes(self._crowd_path)
            _, road_hash, _ = _read_bytes(self._road_network_path)
            sources = self._source_loader()
            traffic_selection = select_strict_as_of(sources.traffic, effective_time)
            crowd_selection = select_strict_as_of(sources.crowd, effective_time)

            bundle = SnapshotBundle(
                effective_event_time=effective_time,
                simulation_clock_time=clock_time,
                traffic=_dynamic_snapshot(
                    traffic_selection,
                    schema_version=sources.traffic.schema_version,
                    content_hash=traffic_hash,
                ),
                crowd=_dynamic_snapshot(
                    crowd_selection,
                    schema_version=sources.crowd.schema_version,
                    content_hash=crowd_hash,
                ),
                road_network=_road_snapshot(
                    sources,
                    requested_as_of=effective_time,
                    content_hash=road_hash,
                ),
                sop=_sop_snapshot(self._sop_path, requested_as_of=effective_time),
            )
            self._bundles[normalized_run_id] = bundle
            return bundle


__all__ = [
    "DEFAULT_CROWD_PATH",
    "DEFAULT_ROAD_NETWORK_PATH",
    "DEFAULT_SOP_PATH",
    "DEFAULT_TRAFFIC_PATH",
    "SOP_SCHEMA_VERSION",
    "SOP_SOURCE",
    "SnapshotService",
    "SnapshotTraceProjection",
    "project_snapshot_trace",
    "resolve_effective_event_time",
]
