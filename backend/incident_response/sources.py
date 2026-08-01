"""Validated source loading and strict as-of selection.

This module deliberately does not build run-scoped ``SnapshotBundle`` objects;
that belongs to the snapshot service.  It provides the immutable, validated
source inputs that service consumes.  Time-series selection is exact/as-of
only: it never interpolates and never falls forward to future data.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Generic, TypeVar

from .domain import UTC_PLUS_8, parse_utc8_datetime

TRAFFIC_SOURCE: Final[str] = "traffic"
CROWD_SOURCE: Final[str] = "crowd"
ROAD_NETWORK_SOURCE: Final[str] = "road_network"
SOURCE_SCHEMA_VERSION: Final[str] = "1.0"

TRAFFIC_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "Timestamp",
        "Segment_ID",
        "Road_Name",
        "Avg_Speed",
        "Vehicle_Count",
        "Saturation_Score",
        "Lane_Status",
    }
)
CROWD_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "Timestamp",
        "BS_ID",
        "Location_Name",
        "User_Count",
        "Stay_Time_Avg",
        "Growth_Rate",
        "Roaming_User_Pct",
    }
)
ROAD_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "segment_id",
        "name",
        "flow_direction",
        "intersections",
        "capacity_vph",
        "alternatives",
        "nearby_stations",
    }
)


@dataclass(frozen=True, slots=True)
class TrafficRecord:
    timestamp: datetime
    segment_id: str
    road_name: str
    avg_speed: float
    vehicle_count: int
    saturation_score: float
    lane_status: str


@dataclass(frozen=True, slots=True)
class CrowdRecord:
    timestamp: datetime
    bs_id: str
    location_name: str
    user_count: int
    stay_time_avg: float
    growth_rate: float
    roaming_user_pct: float


@dataclass(frozen=True, slots=True)
class RoadSegment:
    segment_id: str
    name: str
    flow_direction: str
    intersections: tuple[str, ...]
    capacity_vph: float
    alternatives: tuple[str, ...]
    nearby_stations: tuple[str, ...]


RecordT = TypeVar("RecordT")


@dataclass(frozen=True, slots=True)
class TimeSlice(Generic[RecordT]):
    """All validation evidence for one timestamp in one source."""

    timestamp: datetime
    records: tuple[RecordT, ...]
    row_count: int
    errors: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.row_count > 0 and not self.errors and len(self.records) == self.row_count


@dataclass(frozen=True, slots=True)
class TimeSeriesSource(Generic[RecordT]):
    source: str
    schema_version: str
    slices: tuple[TimeSlice[RecordT], ...]
    source_errors: tuple[str, ...] = ()
    known_ids: frozenset[str] = frozenset()

    @property
    def complete_times(self) -> tuple[datetime, ...]:
        return tuple(time_slice.timestamp for time_slice in self.slices if time_slice.complete)

    @property
    def has_complete_slice(self) -> bool:
        return bool(self.complete_times)


@dataclass(frozen=True, slots=True)
class RoadNetworkSource:
    source: str
    schema_version: str
    records: tuple[RoadSegment, ...]
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return bool(self.records) and not self.errors


@dataclass(frozen=True, slots=True)
class AsOfSelection(Generic[RecordT]):
    source: str
    requested_as_of: datetime
    actual_data_time: datetime | None
    records: tuple[RecordT, ...]
    available: bool
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.available:
            if self.actual_data_time is None or not self.records:
                raise ValueError("available selection requires time and records")
            if self.unavailable_reason is not None:
                raise ValueError("available selection cannot have an unavailable reason")
            if self.actual_data_time > self.requested_as_of:
                raise ValueError("as-of selection cannot contain future data")
        elif self.actual_data_time is not None or self.records or self.unavailable_reason is None:
            raise ValueError("unavailable selection requires only an unavailable reason")


@dataclass(frozen=True, slots=True)
class RepositorySources:
    traffic: TimeSeriesSource[TrafficRecord]
    crowd: TimeSeriesSource[CrowdRecord]
    road_network: RoadNetworkSource

    @property
    def common_complete_timeline(self) -> tuple[datetime, ...]:
        return common_complete_timeline(self.traffic, self.crowd)


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: required non-empty string")
    return value.strip()


def _finite_float(value: Any, path: str, *, minimum: float | None = None) -> float:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError(f"{path}: required number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path}: required number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{path}: required finite number")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{path}: must be >= {minimum:g}")
    return parsed


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError(f"{path}: required integer")
    text = str(value).strip()
    if not text or (text[0] in "+-" and not text[1:].isdigit()) or (
        text[0] not in "+-" and not text.isdigit()
    ):
        raise ValueError(f"{path}: required integer")
    parsed = int(text)
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{path}: must be >= {minimum}")
    return parsed


def _ratio_or_percent(value: Any, path: str) -> float:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError(f"{path}: required ratio or percent")
    text = str(value).strip()
    is_percent = text.endswith("%")
    numeric = text[:-1].strip() if is_percent else text
    parsed = _finite_float(numeric, path)
    ratio = parsed / 100.0 if is_percent else parsed
    if ratio < 0 or ratio > 1:
        raise ValueError(f"{path}: must be between 0 and 1 (or 0% and 100%)")
    return ratio


def _timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{path}: required YYYY-MM-DD HH:MM string")
    try:
        return parse_utc8_datetime(value.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path}: invalid UTC+8 timestamp") from exc


def _parse_traffic_row(row: Mapping[str, Any], row_number: int) -> TrafficRecord:
    prefix = f"traffic[{row_number}]"
    timestamp = _timestamp(row.get("Timestamp"), f"{prefix}.Timestamp")
    saturation = _finite_float(
        row.get("Saturation_Score"), f"{prefix}.Saturation_Score", minimum=0
    )
    if saturation > 1:
        raise ValueError(f"{prefix}.Saturation_Score: must be <= 1")
    return TrafficRecord(
        timestamp=timestamp,
        segment_id=_required_string(row.get("Segment_ID"), f"{prefix}.Segment_ID"),
        road_name=_required_string(row.get("Road_Name"), f"{prefix}.Road_Name"),
        avg_speed=_finite_float(row.get("Avg_Speed"), f"{prefix}.Avg_Speed", minimum=0),
        vehicle_count=_integer(
            row.get("Vehicle_Count"), f"{prefix}.Vehicle_Count", minimum=0
        ),
        saturation_score=saturation,
        lane_status=_required_string(row.get("Lane_Status"), f"{prefix}.Lane_Status"),
    )


def _parse_crowd_row(row: Mapping[str, Any], row_number: int) -> CrowdRecord:
    prefix = f"crowd[{row_number}]"
    return CrowdRecord(
        timestamp=_timestamp(row.get("Timestamp"), f"{prefix}.Timestamp"),
        bs_id=_required_string(row.get("BS_ID"), f"{prefix}.BS_ID"),
        location_name=_required_string(
            row.get("Location_Name"), f"{prefix}.Location_Name"
        ),
        user_count=_integer(row.get("User_Count"), f"{prefix}.User_Count", minimum=0),
        stay_time_avg=_finite_float(
            row.get("Stay_Time_Avg"), f"{prefix}.Stay_Time_Avg", minimum=0
        ),
        growth_rate=_finite_float(row.get("Growth_Rate"), f"{prefix}.Growth_Rate"),
        roaming_user_pct=_ratio_or_percent(
            row.get("Roaming_User_Pct"), f"{prefix}.Roaming_User_Pct"
        ),
    )


def _load_time_series_csv(
    path: str | Path,
    *,
    source: str,
    required_fields: frozenset[str],
    id_field: str,
    parser: Callable[[Mapping[str, Any], int], RecordT],
    record_id: Callable[[RecordT], str],
) -> TimeSeriesSource[RecordT]:
    source_path = Path(path)
    source_errors: list[str] = []
    grouped_rows: dict[datetime, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    known_ids: set[str] = set()

    try:
        handle = source_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        return TimeSeriesSource(
            source=source,
            schema_version=SOURCE_SCHEMA_VERSION,
            slices=(),
            source_errors=(f"{source}: cannot read source ({type(exc).__name__})",),
        )

    with handle:
        reader = csv.DictReader(handle)
        fields = frozenset(reader.fieldnames or ())
        missing = sorted(required_fields - fields)
        if missing:
            return TimeSeriesSource(
                source=source,
                schema_version=SOURCE_SCHEMA_VERSION,
                slices=(),
                source_errors=(f"{source}: missing required columns: {', '.join(missing)}",),
            )

        for row_number, row in enumerate(reader, start=2):
            raw_id = row.get(id_field)
            if isinstance(raw_id, str) and raw_id.strip():
                known_ids.add(raw_id.strip())
            try:
                row_time = _timestamp(row.get("Timestamp"), f"{source}[{row_number}].Timestamp")
            except ValueError as exc:
                source_errors.append(str(exc))
                continue
            grouped_rows[row_time].append((row_number, row))

    slices: list[TimeSlice[RecordT]] = []
    for slice_time in sorted(grouped_rows):
        rows = grouped_rows[slice_time]
        parsed_records: list[RecordT] = []
        errors: list[str] = []
        ids_seen: set[str] = set()
        duplicate_ids: set[str] = set()
        for row_number, row in rows:
            try:
                record = parser(row, row_number)
                parsed_records.append(record)
                identifier = record_id(record)
                if identifier in ids_seen:
                    duplicate_ids.add(identifier)
                ids_seen.add(identifier)
            except ValueError as exc:
                errors.append(str(exc))
        for identifier in sorted(duplicate_ids):
            errors.append(
                f"{source}[{slice_time.strftime('%Y-%m-%d %H:%M')}].{id_field}: "
                f"duplicate identifier {identifier}"
            )
        slices.append(
            TimeSlice(
                timestamp=slice_time,
                records=tuple(parsed_records) if not errors else (),
                row_count=len(rows),
                errors=tuple(errors),
            )
        )

    if not grouped_rows and not source_errors:
        source_errors.append(f"{source}: source contains no records")
    return TimeSeriesSource(
        source=source,
        schema_version=SOURCE_SCHEMA_VERSION,
        slices=tuple(slices),
        source_errors=tuple(source_errors),
        known_ids=frozenset(known_ids),
    )


def load_traffic_source(path: str | Path) -> TimeSeriesSource[TrafficRecord]:
    """Load traffic CSV and validate each timestamp independently."""

    return _load_time_series_csv(
        path,
        source=TRAFFIC_SOURCE,
        required_fields=TRAFFIC_REQUIRED_FIELDS,
        id_field="Segment_ID",
        parser=_parse_traffic_row,
        record_id=lambda record: record.segment_id,
    )


def load_crowd_source(path: str | Path) -> TimeSeriesSource[CrowdRecord]:
    """Load crowd CSV and normalize roaming percentages to a 0..1 ratio."""

    return _load_time_series_csv(
        path,
        source=CROWD_SOURCE,
        required_fields=CROWD_REQUIRED_FIELDS,
        id_field="BS_ID",
        parser=_parse_crowd_row,
        record_id=lambda record: record.bs_id,
    )


def _string_list(value: Any, path: str, *, require_non_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{path}: required array")
    if require_non_empty and not value:
        raise ValueError(f"{path}: requires at least one entry")
    result = tuple(_required_string(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise ValueError(f"{path}: entries must be unique and ordered")
    return result


def load_road_network(
    path: str | Path, *, known_station_ids: Collection[str]
) -> RoadNetworkSource:
    """Load and validate the static road graph and all cross-source references."""

    source_path = Path(path)
    try:
        raw_bytes = source_path.read_bytes()
    except OSError as exc:
        return RoadNetworkSource(
            source=ROAD_NETWORK_SOURCE,
            schema_version=SOURCE_SCHEMA_VERSION,
            records=(),
            errors=(f"road_network: cannot read source ({type(exc).__name__})",),
        )
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return RoadNetworkSource(
            source=ROAD_NETWORK_SOURCE,
            schema_version=SOURCE_SCHEMA_VERSION,
            records=(),
            errors=("road_network: source must be valid UTF-8 JSON",),
        )
    if not isinstance(value, list) or not value:
        return RoadNetworkSource(
            source=ROAD_NETWORK_SOURCE,
            schema_version=SOURCE_SCHEMA_VERSION,
            records=(),
            errors=("road_network: top level must be a non-empty array",),
        )

    errors: list[str] = []
    parsed: list[RoadSegment] = []
    raw_segment_ids: list[str] = []
    for index, item in enumerate(value):
        prefix = f"road_network[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: required object")
            continue
        missing = sorted(ROAD_REQUIRED_FIELDS - item.keys())
        if missing:
            errors.append(f"{prefix}: missing required fields: {', '.join(missing)}")
            continue
        try:
            segment_id = _required_string(item.get("segment_id"), f"{prefix}.segment_id")
            raw_segment_ids.append(segment_id)
            parsed.append(
                RoadSegment(
                    segment_id=segment_id,
                    name=_required_string(item.get("name"), f"{prefix}.name"),
                    flow_direction=_required_string(
                        item.get("flow_direction"), f"{prefix}.flow_direction"
                    ),
                    intersections=_string_list(
                        item.get("intersections"),
                        f"{prefix}.intersections",
                        require_non_empty=True,
                    ),
                    capacity_vph=_finite_float(
                        item.get("capacity_vph"), f"{prefix}.capacity_vph", minimum=0
                    ),
                    alternatives=_string_list(
                        item.get("alternatives"),
                        f"{prefix}.alternatives",
                        require_non_empty=False,
                    ),
                    nearby_stations=_string_list(
                        item.get("nearby_stations"),
                        f"{prefix}.nearby_stations",
                        require_non_empty=False,
                    ),
                )
            )
        except ValueError as exc:
            errors.append(str(exc))

    duplicate_ids = sorted(
        identifier for identifier in set(raw_segment_ids) if raw_segment_ids.count(identifier) > 1
    )
    for identifier in duplicate_ids:
        errors.append(f"road_network.segment_id: duplicate identifier {identifier}")

    road_ids = set(raw_segment_ids)
    station_ids = {identifier.strip() for identifier in known_station_ids if identifier.strip()}
    for segment in parsed:
        for alternative in segment.alternatives:
            if alternative not in road_ids:
                errors.append(
                    f"road_network[{segment.segment_id}].alternatives: unknown segment {alternative}"
                )
            elif alternative == segment.segment_id:
                errors.append(
                    f"road_network[{segment.segment_id}].alternatives: cannot reference itself"
                )
        for station in segment.nearby_stations:
            if station not in station_ids:
                errors.append(
                    f"road_network[{segment.segment_id}].nearby_stations: unknown station {station}"
                )

    return RoadNetworkSource(
        source=ROAD_NETWORK_SOURCE,
        schema_version=SOURCE_SCHEMA_VERSION,
        records=tuple(parsed),
        errors=tuple(errors),
    )


def _normalize_as_of(value: datetime | str) -> datetime:
    if isinstance(value, str):
        return parse_utc8_datetime(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("effective_event_time must be timezone-aware")
    return value.astimezone(UTC_PLUS_8)


def select_strict_as_of(
    source: TimeSeriesSource[RecordT], effective_event_time: datetime | str
) -> AsOfSelection[RecordT]:
    """Select the latest complete source slice at or before the event time.

    Invalid slices are ignored.  If there is no complete past slice, the result
    is unavailable even when future slices exist.
    """

    requested = _normalize_as_of(effective_event_time)
    eligible = [
        time_slice
        for time_slice in source.slices
        if time_slice.complete and time_slice.timestamp <= requested
    ]
    if not eligible:
        reason = f"{source.source}: no complete time slice at or before effective event time"
        if source.source_errors:
            reason = f"{reason}; {'; '.join(source.source_errors)}"
        return AsOfSelection(
            source=source.source,
            requested_as_of=requested,
            actual_data_time=None,
            records=(),
            available=False,
            unavailable_reason=reason,
        )
    selected = max(eligible, key=lambda time_slice: time_slice.timestamp)
    return AsOfSelection(
        source=source.source,
        requested_as_of=requested,
        actual_data_time=selected.timestamp,
        records=selected.records,
        available=True,
    )


def common_complete_timeline(
    traffic: TimeSeriesSource[Any], crowd: TimeSeriesSource[Any]
) -> tuple[datetime, ...]:
    """Return the ascending intersection of complete traffic/crowd slices."""

    return tuple(sorted(set(traffic.complete_times) & set(crowd.complete_times)))


def load_repository_sources(
    *, traffic_path: str | Path, crowd_path: str | Path, road_network_path: str | Path
) -> RepositorySources:
    """Load all repository sources using crowd IDs for road reference checks."""

    traffic = load_traffic_source(traffic_path)
    crowd = load_crowd_source(crowd_path)
    road_network = load_road_network(
        road_network_path, known_station_ids=crowd.known_ids
    )
    return RepositorySources(traffic=traffic, crowd=crowd, road_network=road_network)


__all__ = [
    "AsOfSelection",
    "CROWD_REQUIRED_FIELDS",
    "CROWD_SOURCE",
    "CrowdRecord",
    "ROAD_NETWORK_SOURCE",
    "ROAD_REQUIRED_FIELDS",
    "RepositorySources",
    "RoadNetworkSource",
    "RoadSegment",
    "SOURCE_SCHEMA_VERSION",
    "TRAFFIC_REQUIRED_FIELDS",
    "TRAFFIC_SOURCE",
    "TimeSeriesSource",
    "TimeSlice",
    "TrafficRecord",
    "common_complete_timeline",
    "load_crowd_source",
    "load_repository_sources",
    "load_road_network",
    "load_traffic_source",
    "select_strict_as_of",
]
