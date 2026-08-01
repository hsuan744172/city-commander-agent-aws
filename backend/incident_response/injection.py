"""Administrator event injection surface for ``live_incidents.json`` payloads.

An administrator injects the same document the field operators produce: a JSON
array of events such as 路面塌陷 (road collapse) or 號誌故障 (signal failure).
This module turns that document into an operator-facing flow while delegating
every rule it can:

* ``IncidentPayloadParser`` stays the only validation and classification
  authority, so the injection API and the upload API cannot drift apart.
* Previews list *candidate* SOP articles only. The Policy Agent remains the sole
  authority on what actually triggers.
* No mathematics happens here; numeric decisions belong to
  ``backend/agents/traffic_math.py``.

The service also owns the confirm-before-execute gate. Injection starts an agent
run and pushes to every connected dashboard, so it is deliberately not a
single-click action: the preview hash and the required confirmations must be
echoed back before the payload is accepted.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .domain import (
    ApiError,
    ApiErrorDetail,
    EventCategory,
    IncidentPayload,
    IncidentPreview,
    PreviewConfirmation,
    PreviewEventSummary,
    SourceLabel,
    UTC_PLUS_8,
    parse_utc8_datetime,
    project_utc8_datetime,
)
from .payload import (
    MAX_INCIDENT_RECORDS,
    MAX_UPLOAD_BYTES,
    IncidentPayloadParser,
    IncidentPayloadValidationError,
    IncidentReferenceCatalog,
    canonical_sha256,
)
from .snapshot import (
    CROWD_FILENAME,
    PROJECT_ROOT,
    ROAD_NETWORK_FILENAME,
    TRAFFIC_FILENAME,
)
from .sources import RepositorySources, load_repository_sources

TEMPLATES_FILENAME: Final[str] = "live_incidents.json"
DEFAULT_CACHE_SECONDS: Final[float] = 60.0
DEFAULT_PREVIEW_TTL_SECONDS: Final[int] = 300
DEFAULT_HISTORY_LIMIT: Final[int] = 20

# Candidate articles per category, used to tell an administrator what a payload
# is likely to trigger before any agent runs. Article 6 (multi-language public
# notice) depends on the roaming ratio at execution time, so it is a candidate
# for every category. The Policy Agent decides the real outcome.
CANDIDATE_SOP_ARTICLES: Final[Mapping[EventCategory, tuple[int, ...]]] = MappingProxyType(
    {
        EventCategory.ROAD_DISRUPTION: (2, 6),
        EventCategory.CROWD_SURGE: (3, 6),
        EventCategory.SIGNAL_FAILURE: (5, 6),
    }
)

CATEGORY_LABELS: Final[Mapping[EventCategory, str]] = MappingProxyType(
    {
        EventCategory.ROAD_DISRUPTION: "路面阻斷",
        EventCategory.CROWD_SURGE: "人流激增",
        EventCategory.SIGNAL_FAILURE: "號誌故障",
    }
)


class InjectionConfirmationError(ValueError):
    """The caller did not echo back everything the preview required."""

    code: Final[str] = "INCIDENT_CONFIRMATION_REQUIRED"

    def __init__(self, *, missing: Iterable[str], message: str) -> None:
        self.missing = tuple(missing)
        super().__init__(message)

    def as_api_error(self, *, trace_id: str) -> ApiError:
        return ApiError(
            code=self.code,
            message=str(self),
            trace_id=trace_id,
            details=tuple(
                ApiErrorDetail(
                    path="confirmations",
                    code="confirmation_missing",
                    message=f"缺少確認項目：{item}",
                )
                for item in self.missing
            ),
        )


class PreviewMismatchError(ValueError):
    """The submitted payload no longer matches the preview that was confirmed."""

    code: Final[str] = "INCIDENT_PREVIEW_MISMATCH"

    def __init__(self, *, expected: str, received: str) -> None:
        self.expected = expected
        self.received = received
        super().__init__("事件內容已變更，請重新驗證後再注入")

    def as_api_error(self, *, trace_id: str) -> ApiError:
        return ApiError(
            code=self.code,
            message=str(self),
            trace_id=trace_id,
            details=(
                ApiErrorDetail(
                    path="preview_hash",
                    code="preview_hash_mismatch",
                    message=f"預期 {self.expected}",
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class InjectableSegment:
    """One road segment an event may reference."""

    segment_id: str
    name: str
    flow_direction: str
    capacity_vph: float


@dataclass(frozen=True, slots=True)
class InjectableStation:
    """One crowd observation station an event may reference."""

    bs_id: str
    location_name: str


@dataclass(frozen=True, slots=True)
class InjectionCatalog:
    """Everything an operator UI needs to compose a valid injection payload."""

    segments: tuple[InjectableSegment, ...]
    stations: tuple[InjectableStation, ...]
    templates: tuple[Mapping[str, Any], ...]
    severities: tuple[str, ...]
    road_status_values: tuple[str, ...]
    references: IncidentReferenceCatalog
    source_errors: tuple[str, ...] = ()
    template_error: str | None = None

    def as_api_dict(self) -> dict[str, Any]:
        return {
            "segments": [
                {
                    "segment_id": segment.segment_id,
                    "name": segment.name,
                    "flow_direction": segment.flow_direction,
                    "capacity_vph": segment.capacity_vph,
                }
                for segment in self.segments
            ],
            "stations": [
                {"bs_id": station.bs_id, "location_name": station.location_name}
                for station in self.stations
            ],
            "templates": [dict(template) for template in self.templates],
            "severities": list(self.severities),
            "road_status_values": list(self.road_status_values),
            "categories": [
                {
                    "category": category.value,
                    "label": CATEGORY_LABELS[category],
                    "candidate_sop_articles": list(articles),
                }
                for category, articles in CANDIDATE_SOP_ARTICLES.items()
            ],
            "max_records": MAX_INCIDENT_RECORDS,
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "source_errors": list(self.source_errors),
            "template_error": self.template_error,
        }


@dataclass(frozen=True, slots=True)
class InjectionRecord:
    """One completed injection, retained in memory for the operator history."""

    injection_id: str
    session_id: str
    source_label: str
    preview_hash: str
    payload_hash: str
    event_ids: tuple[str, ...]
    simulation_clock_time: str
    injected_at: str
    report: Mapping[str, Any]

    def as_api_dict(self, *, include_report: bool = True) -> dict[str, Any]:
        summary = {
            "injection_id": self.injection_id,
            "session_id": self.session_id,
            "source_label": self.source_label,
            "preview_hash": self.preview_hash,
            "payload_hash": self.payload_hash,
            "event_ids": list(self.event_ids),
            "simulation_clock_time": self.simulation_clock_time,
            "injected_at": self.injected_at,
        }
        if include_report:
            summary["report"] = dict(self.report)
        return summary


class EventInjectionService:
    """Catalog, preview, and history for administrator-driven event injection."""

    def __init__(
        self,
        *,
        traffic_path: str | Path | None = None,
        crowd_path: str | Path | None = None,
        road_network_path: str | Path | None = None,
        templates_path: str | Path | None = None,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        preview_ttl_seconds: int = DEFAULT_PREVIEW_TTL_SECONDS,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        if preview_ttl_seconds <= 0:
            raise ValueError("preview_ttl_seconds must be positive")
        if history_limit <= 0:
            raise ValueError("history_limit must be positive")
        self._traffic_path = traffic_path
        self._crowd_path = crowd_path
        self._road_network_path = road_network_path
        self._templates_path = templates_path
        self._cache_seconds = max(0.0, cache_seconds)
        self._preview_ttl = timedelta(seconds=preview_ttl_seconds)
        self._lock = threading.Lock()
        self._cached: InjectionCatalog | None = None
        self._cached_at: float = 0.0
        self._history: deque[InjectionRecord] = deque(maxlen=history_limit)

    # -- catalog ------------------------------------------------------------

    def catalog(self, *, refresh: bool = False) -> InjectionCatalog:
        """Return the injectable identifiers and templates, cached briefly.

        Data files can be served from the S3 cache, so the catalog is rebuilt on
        a short interval rather than pinned for the process lifetime.
        """

        now = time.monotonic()
        with self._lock:
            fresh = (
                self._cached is not None
                and not refresh
                and now - self._cached_at < self._cache_seconds
            )
            if fresh:
                assert self._cached is not None
                return self._cached
            catalog = self._build_catalog()
            self._cached = catalog
            self._cached_at = now
            return catalog

    def parser(self, *, refresh: bool = False) -> IncidentPayloadParser:
        """Return a parser bound to the currently known identifiers."""

        return IncidentPayloadParser(self.catalog(refresh=refresh).references)

    # -- preview ------------------------------------------------------------

    def preview_json(
        self,
        value: Any,
        *,
        simulation_clock_time: datetime | str,
        created_at: datetime | None = None,
    ) -> IncidentPreview:
        """Validate an already-decoded payload and build its preview."""

        payload = self.parser().validate(value)
        return self._preview_for(
            payload,
            simulation_clock_time=simulation_clock_time,
            created_at=created_at,
        )

    def preview_upload(
        self,
        *,
        filename: str,
        content: bytes,
        simulation_clock_time: datetime | str,
        created_at: datetime | None = None,
    ) -> IncidentPreview:
        """Apply the upload rules, then build the same preview as direct JSON."""

        payload = self.parser().parse_upload(filename=filename, content=content)
        return self._preview_for(
            payload,
            simulation_clock_time=simulation_clock_time,
            created_at=created_at,
        )

    def _preview_for(
        self,
        payload: IncidentPayload,
        *,
        simulation_clock_time: datetime | str,
        created_at: datetime | None,
    ) -> IncidentPreview:
        clock_time = _normalize_time(simulation_clock_time)
        created = created_at or datetime.now(tz=UTC_PLUS_8)
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

        summaries = tuple(
            PreviewEventSummary(
                original_index=record.original_index,
                event_id=record.event_id,
                category=record.category,
                location=record.location,
                affected_segment=record.affected_segment,
                severity=record.severity,
                timestamp=record.timestamp,
                possible_sop_articles=CANDIDATE_SOP_ARTICLES[
                    EventCategory(record.category)
                ],
            )
            for record in payload.incidents
        )
        contains_future_event = any(
            record.effective_event_time > clock_time for record in payload.incidents
        )
        confirmations: list[PreviewConfirmation] = [PreviewConfirmation.PAYLOAD]
        if contains_future_event:
            confirmations.append(PreviewConfirmation.FUTURE_SIMULATION)

        preview_hash = preview_hash_for(
            payload,
            source_label=SourceLabel.JSON_UPLOAD,
            simulation_clock_time=clock_time,
        )
        return IncidentPreview(
            preview_id=f"prv_{preview_hash[:24]}",
            preview_hash=preview_hash,
            source_label=SourceLabel.JSON_UPLOAD,
            normalized_payload=payload,
            event_summaries=summaries,
            created_at=created,
            expires_at=created + self._preview_ttl,
            simulation_clock_time=clock_time,
            contains_future_event=contains_future_event,
            required_confirmations=tuple(confirmations),
        )

    # -- confirmation gate --------------------------------------------------

    @staticmethod
    def verify_preview_hash(preview: IncidentPreview, submitted: str | None) -> None:
        """Reject a payload that was edited after the operator reviewed it."""

        if submitted is None or not submitted.strip():
            return
        if submitted.strip().casefold() != preview.preview_hash:
            raise PreviewMismatchError(
                expected=preview.preview_hash,
                received=submitted.strip(),
            )

    @staticmethod
    def verify_confirmations(
        preview: IncidentPreview, confirmations: Sequence[str] | None
    ) -> None:
        """Require every confirmation the preview asked for, by exact name."""

        supplied = {
            item.strip()
            for item in (confirmations or ())
            if isinstance(item, str) and item.strip()
        }
        required = {
            PreviewConfirmation(item).value for item in preview.required_confirmations
        }
        missing = sorted(required - supplied)
        if not missing:
            return
        raise InjectionConfirmationError(
            missing=missing,
            message="注入前必須確認事件內容"
            + ("與未來時間情境" if PreviewConfirmation.FUTURE_SIMULATION.value in missing else ""),
        )

    # -- history ------------------------------------------------------------

    def record_injection(
        self,
        *,
        preview: IncidentPreview,
        session_id: str,
        report: Mapping[str, Any],
        injected_at: datetime | None = None,
    ) -> InjectionRecord:
        """Retain a completed injection so reloaded dashboards can catch up."""

        moment = injected_at or datetime.now(tz=UTC_PLUS_8)
        record = InjectionRecord(
            injection_id=f"inj_{preview.preview_hash[:16]}_{int(moment.timestamp())}",
            session_id=session_id,
            source_label=SourceLabel(preview.source_label).value,
            preview_hash=preview.preview_hash,
            payload_hash=preview.normalized_payload.normalized_hash,
            event_ids=tuple(
                record.event_id for record in preview.normalized_payload.incidents
            ),
            simulation_clock_time=project_utc8_datetime(preview.simulation_clock_time),
            injected_at=project_utc8_datetime(moment),
            report=dict(report),
        )
        with self._lock:
            self._history.appendleft(record)
        return record

    def recent_injections(self, *, limit: int | None = None) -> tuple[InjectionRecord, ...]:
        """Return injections newest-first, optionally truncated."""

        with self._lock:
            records = tuple(self._history)
        if limit is None:
            return records
        if limit < 0:
            raise ValueError("limit cannot be negative")
        return records[:limit]

    # -- internals ----------------------------------------------------------

    def _build_catalog(self) -> InjectionCatalog:
        sources = load_repository_sources(
            traffic_path=_resolve_data_path(self._traffic_path, TRAFFIC_FILENAME),
            crowd_path=_resolve_data_path(self._crowd_path, CROWD_FILENAME),
            road_network_path=_resolve_data_path(
                self._road_network_path, ROAD_NETWORK_FILENAME
            ),
        )
        segments = tuple(
            InjectableSegment(
                segment_id=segment.segment_id,
                name=segment.name,
                flow_direction=segment.flow_direction,
                capacity_vph=segment.capacity_vph,
            )
            for segment in sorted(
                sources.road_network.records, key=lambda item: item.segment_id
            )
        )
        stations = _stations_from(sources)
        references = IncidentReferenceCatalog(
            road_segment_ids=(segment.segment_id for segment in segments),
            crowd_station_ids=sources.crowd.known_ids,
        )
        templates, template_error = self._load_templates(references)
        return InjectionCatalog(
            segments=segments,
            stations=stations,
            templates=templates,
            severities=("Critical", "High", "Medium"),
            road_status_values=("Closed", "Blocked", "Restricted"),
            references=references,
            source_errors=tuple(
                (
                    *sources.traffic.source_errors,
                    *sources.crowd.source_errors,
                    *sources.road_network.errors,
                )
            ),
            template_error=template_error,
        )

    def _load_templates(
        self, references: IncidentReferenceCatalog
    ) -> tuple[tuple[Mapping[str, Any], ...], str | None]:
        """Publish ``live_incidents.json`` as pre-fill templates.

        A template is only useful if it would actually pass validation, so the
        file goes through the real parser. A broken file degrades the catalog
        instead of failing it: the operator can still compose a payload by hand.
        """

        path = _resolve_data_path(self._templates_path, TEMPLATES_FILENAME)
        try:
            raw = Path(path).read_bytes()
        except OSError:
            return (), f"無法讀取事件範本檔案 {TEMPLATES_FILENAME}"

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return (), f"{TEMPLATES_FILENAME} 不是有效的 UTF-8 JSON"

        raw_records = (
            decoded["incidents"]
            if isinstance(decoded, Mapping) and isinstance(decoded.get("incidents"), list)
            else decoded
        )
        if not isinstance(raw_records, list):
            return (), f"{TEMPLATES_FILENAME} 頂層必須是事件陣列"

        try:
            payload = IncidentPayloadParser(references).validate(raw_records)
        except IncidentPayloadValidationError as exc:
            return (), f"{TEMPLATES_FILENAME} 未通過驗證：{exc.message}"

        templates = tuple(
            MappingProxyType(
                {
                    **{
                        key: value
                        for key, value in record.model_dump(mode="json").items()
                        if key not in {"category", "original_index"} and value is not None
                    },
                    "_category": EventCategory(record.category).value,
                    "_category_label": CATEGORY_LABELS[EventCategory(record.category)],
                }
            )
            for record in payload.incidents
        )
        return templates, None


def preview_hash_for(
    payload: IncidentPayload,
    *,
    source_label: SourceLabel | str,
    simulation_clock_time: datetime | str,
) -> str:
    """Derive a preview hash that any process can recompute from the inputs.

    Binding the simulation clock into the hash means a preview cannot be
    replayed against a different clock position than the one it was reviewed at.
    """

    label = (
        source_label if isinstance(source_label, SourceLabel) else SourceLabel(source_label)
    )
    return canonical_sha256(
        {
            "payload_hash": payload.normalized_hash,
            "simulation_clock_time": project_utc8_datetime(
                _normalize_time(simulation_clock_time)
            ),
            "source_label": label.value,
        }
    )


def _resolve_data_path(explicit: str | Path | None, filename: str) -> Path:
    """Pin an explicit path, or resolve S3-first with a local ``data/`` fallback."""

    if explicit is not None:
        return Path(explicit)
    try:
        from backend.data_source import get_data_path

        return get_data_path(filename)
    except Exception:  # pragma: no cover - the packaged data must still work
        return PROJECT_ROOT / "data" / filename


def _normalize_time(value: datetime | str) -> datetime:
    if isinstance(value, str):
        return parse_utc8_datetime(value)
    if not isinstance(value, datetime):
        raise TypeError("time must be a datetime or YYYY-MM-DD HH:MM string")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC_PLUS_8)
    return value.astimezone(UTC_PLUS_8)


def _stations_from(sources: RepositorySources) -> tuple[InjectableStation, ...]:
    """Name each station from its most recent complete crowd slice."""

    names: dict[str, str] = {}
    for time_slice in sources.crowd.slices:
        if not time_slice.complete:
            continue
        for record in time_slice.records:
            names[record.bs_id] = record.location_name
    return tuple(
        InjectableStation(bs_id=bs_id, location_name=names.get(bs_id, bs_id))
        for bs_id in sorted(sources.crowd.known_ids)
    )


__all__ = [
    "CANDIDATE_SOP_ARTICLES",
    "CATEGORY_LABELS",
    "DEFAULT_CACHE_SECONDS",
    "DEFAULT_HISTORY_LIMIT",
    "DEFAULT_PREVIEW_TTL_SECONDS",
    "EventInjectionService",
    "InjectableSegment",
    "InjectableStation",
    "InjectionCatalog",
    "InjectionConfirmationError",
    "InjectionRecord",
    "PreviewMismatchError",
    "TEMPLATES_FILENAME",
    "preview_hash_for",
]
