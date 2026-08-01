"""Shared incident payload parsing, domain validation, and canonical hashing.

Both already-decoded JSON request bodies and uploaded JSON documents terminate in
``IncidentPayloadParser.validate`` so their shape and domain rules cannot drift.
The module performs no API or persistence work; callers supply the currently
known road and crowd identifiers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Final

from pydantic import ValidationError

from .config import CONTRACT_VERSION
from .domain import (
    ApiError,
    ApiErrorDetail,
    EventCategory,
    FrozenStrictModel,
    IncidentPayload,
    IncidentRecord,
    IncidentTimestamp,
    SeverityValue,
    TrimmedString120,
    TrimmedString500,
    TrimmedString64,
)

MIN_UPLOAD_BYTES: Final[int] = 1
MAX_UPLOAD_BYTES: Final[int] = 1_048_576
MAX_INCIDENT_RECORDS: Final[int] = 100


@dataclass(frozen=True, slots=True)
class IncidentReferenceCatalog:
    """Identifiers that are valid for incident category references."""

    road_segment_ids: frozenset[str]
    crowd_station_ids: frozenset[str]

    def __init__(
        self,
        road_segment_ids: Iterable[str],
        crowd_station_ids: Iterable[str],
    ) -> None:
        roads = _validated_reference_ids(road_segment_ids, "road_segment_ids")
        stations = _validated_reference_ids(crowd_station_ids, "crowd_station_ids")
        object.__setattr__(self, "road_segment_ids", roads)
        object.__setattr__(self, "crowd_station_ids", stations)


class IncidentPayloadValidationError(ValueError):
    """A safe, structured batch validation failure.

    ``details`` contains only contract paths, stable codes, and controlled
    messages. Raw payloads, parser exception text, stack traces, and file paths
    are deliberately not retained.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Iterable[ApiErrorDetail],
    ) -> None:
        self.code = code
        self.message = message
        self.details = tuple(details)
        super().__init__(message)

    def as_api_error(self, *, trace_id: str) -> ApiError:
        return ApiError(
            code=self.code,
            message=self.message,
            trace_id=trace_id,
            details=self.details,
        )


class _IncidentRecordInput(FrozenStrictModel):
    event_id: TrimmedString64
    type: TrimmedString64
    location: TrimmedString120
    affected_segment: TrimmedString64
    severity: SeverityValue
    description: TrimmedString500
    timestamp: IncidentTimestamp
    status: TrimmedString64 | None = None
    affected_road: TrimmedString64 | None = None


class IncidentPayloadParser:
    """Parse and validate incident payloads against one reference catalog."""

    def __init__(self, references: IncidentReferenceCatalog) -> None:
        self._references = references

    def parse(self, raw_json: str | bytes | bytearray) -> IncidentPayload:
        """Decode a JSON document and apply the shared payload validator."""

        text = _decode_json_text(raw_json)
        try:
            value = json.loads(text, parse_constant=_reject_non_json_constant)
        except (json.JSONDecodeError, ValueError):
            raise _single_error(
                code="INCIDENT_JSON_MALFORMED",
                message="JSON 內容無法解析",
                path="$",
                detail_code="malformed_json",
                detail_message="請提供有效的 JSON 文件",
            ) from None
        return self.validate(value)

    def validate(self, value: Any) -> IncidentPayload:
        """Validate an already-decoded JSON value and return normalized input."""

        raw_records = _extract_records(value)
        errors: list[ApiErrorDetail] = []
        records: list[IncidentRecord] = []
        event_id_locations: dict[str, list[int]] = {}

        for index, candidate in enumerate(raw_records):
            base_path = f"incidents[{index}]"
            if not isinstance(candidate, Mapping):
                errors.append(
                    ApiErrorDetail(
                        path=base_path,
                        code="object_type",
                        message="每筆事件必須是 JSON 物件",
                    )
                )
                continue

            candidate_dict = dict(candidate)
            field_errors = _record_field_errors(candidate_dict, index)
            errors.extend(field_errors)
            invalid_fields = {
                _first_location_part(error[0])
                for error in _raw_validation_errors(candidate_dict)
            }

            event_id = candidate_dict.get("event_id")
            if (
                "event_id" not in invalid_fields
                and isinstance(event_id, str)
                and 1 <= len(event_id.strip()) <= 64
            ):
                event_id_locations.setdefault(event_id.strip(), []).append(index)

            category_errors: list[ApiErrorDetail] = []
            classification_fields = {"type", "description", "affected_segment"}
            if invalid_fields.isdisjoint(classification_fields):
                incident_type = _normalized_string(candidate_dict.get("type"))
                description = _normalized_string(candidate_dict.get("description"))
                affected_segment = _normalized_string(
                    candidate_dict.get("affected_segment")
                )
                category, category_errors = self._classify_and_validate_reference(
                    index=index,
                    incident_type=incident_type,
                    description=description,
                    affected_segment=affected_segment,
                )
                errors.extend(category_errors)
                if category is not None and "status" not in invalid_fields:
                    errors.extend(
                        _validate_status(
                            index=index,
                            category=category,
                            status=candidate_dict.get("status"),
                        )
                    )
            else:
                category = None

            road_ref_errors: list[ApiErrorDetail] = []
            if "affected_road" not in invalid_fields:
                road_ref_errors = self._validate_affected_road(
                    index=index,
                    affected_road=candidate_dict.get("affected_road"),
                )
                errors.extend(road_ref_errors)

            if (
                not field_errors
                and not category_errors
                and not road_ref_errors
                and category is not None
            ):
                status_errors = _validate_status(
                    index=index,
                    category=category,
                    status=candidate_dict.get("status"),
                )
                if not status_errors:
                    normalized = _IncidentRecordInput.model_validate(candidate_dict)
                    records.append(
                        IncidentRecord(
                            **normalized.model_dump(mode="python"),
                            category=category,
                            original_index=index,
                        )
                    )

        for event_id, indices in event_id_locations.items():
            if len(indices) < 2:
                continue
            for index in indices:
                errors.append(
                    ApiErrorDetail(
                        path=f"incidents[{index}].event_id",
                        code="duplicate_event_id",
                        message=f"event_id 重複：{event_id}",
                    )
                )

        if errors:
            raise IncidentPayloadValidationError(
                code="INCIDENT_PAYLOAD_INVALID",
                message="事件內容驗證失敗",
                details=errors,
            )

        canonical_value = {
            "contract_version": CONTRACT_VERSION,
            "incidents": [record.model_dump(mode="json") for record in records],
        }
        normalized_hash = canonical_sha256(canonical_value)
        return IncidentPayload(
            incidents=tuple(records),
            normalized_hash=normalized_hash,
        )

    def parse_upload(self, *, filename: str, content: bytes) -> IncidentPayload:
        """Enforce upload rules before using the same JSON/domain parser."""

        if not isinstance(filename, str) or PurePath(filename).suffix.casefold() != ".json":
            raise _single_error(
                code="INCIDENT_FILE_TYPE_INVALID",
                message="僅接受 .json 檔案",
                path="$file",
                detail_code="file_extension",
                detail_message="檔案副檔名必須為 .json",
            )
        if not isinstance(content, bytes):
            raise TypeError("upload content must be bytes")
        if len(content) < MIN_UPLOAD_BYTES:
            raise _single_error(
                code="INCIDENT_FILE_EMPTY",
                message="上傳檔案不可為空",
                path="$file",
                detail_code="file_size_min",
                detail_message="檔案大小至少須為 1 byte",
            )
        if len(content) > MAX_UPLOAD_BYTES:
            raise _single_error(
                code="INCIDENT_FILE_TOO_LARGE",
                message="上傳檔案超過大小上限",
                path="$file",
                detail_code="file_size_max",
                detail_message="檔案大小不可超過 1,048,576 bytes",
            )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise _single_error(
                code="INCIDENT_FILE_ENCODING_INVALID",
                message="上傳檔案必須使用 UTF-8 編碼",
                path="$file",
                detail_code="utf8",
                detail_message="檔案不是有效的 UTF-8 內容",
            ) from None
        if text.startswith("\ufeff"):
            text = text[1:]
        return self.parse(text)

    def _validate_affected_road(
        self, *, index: int, affected_road: Any
    ) -> list[ApiErrorDetail]:
        """Validate the optional secondary road reference when it is supplied."""

        if affected_road is None:
            return []
        normalized = _normalized_string(affected_road)
        if normalized and normalized in self._references.road_segment_ids:
            return []
        return [
            ApiErrorDetail(
                path=f"incidents[{index}].affected_road",
                code="road_segment_unknown",
                message="affected_road 必須是已知的 RD_ 路段",
            )
        ]

    def _classify_and_validate_reference(
        self,
        *,
        index: int,
        incident_type: str,
        description: str,
        affected_segment: str,
    ) -> tuple[EventCategory | None, list[ApiErrorDetail]]:
        base = f"incidents[{index}]"
        signal_by_type = incident_type == "Power_Failure"
        signal_by_description = "號誌失效" in description or "故障" in description
        is_signal = signal_by_type or signal_by_description
        is_crowd = affected_segment.startswith("BS_")
        is_road = (
            affected_segment.startswith("RD_")
            and not signal_by_type
            and not signal_by_description
        )
        categories = [
            category
            for category, matched in (
                (EventCategory.ROAD_DISRUPTION, is_road),
                (EventCategory.CROWD_SURGE, is_crowd),
                (EventCategory.SIGNAL_FAILURE, is_signal),
            )
            if matched
        ]

        if len(categories) > 1:
            conflict_paths = [f"{base}.affected_segment"]
            if signal_by_type:
                conflict_paths.append(f"{base}.type")
            if signal_by_description:
                conflict_paths.append(f"{base}.description")
            return None, [
                ApiErrorDetail(
                    path=path,
                    code="category_conflict",
                    message="事件同時符合多個分類",
                )
                for path in conflict_paths
            ]
        if not categories:
            return None, [
                ApiErrorDetail(
                    path=f"{base}.type",
                    code="category_unclassified",
                    message="type 與 affected_segment 無法形成唯一事件分類",
                ),
                ApiErrorDetail(
                    path=f"{base}.affected_segment",
                    code="category_unclassified",
                    message="type 與 affected_segment 無法形成唯一事件分類",
                ),
            ]

        category = categories[0]
        if category is EventCategory.CROWD_SURGE:
            if affected_segment not in self._references.crowd_station_ids:
                return category, [
                    ApiErrorDetail(
                        path=f"{base}.affected_segment",
                        code="crowd_station_unknown",
                        message="affected_segment 必須是已知的 BS_ 站點",
                    )
                ]
        elif affected_segment not in self._references.road_segment_ids:
            return category, [
                ApiErrorDetail(
                    path=f"{base}.affected_segment",
                    code="road_segment_unknown",
                    message="affected_segment 必須是已知的 RD_ 路段",
                )
            ]
        return category, []


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON data deterministically without reordering arrays."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON data") from exc
    return text.encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return lowercase SHA-256 for the canonical UTF-8 JSON representation."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def parse_payload(
    raw_json: str | bytes | bytearray,
    references: IncidentReferenceCatalog,
) -> IncidentPayload:
    """Convenience entry point for a raw JSON document."""

    return IncidentPayloadParser(references).parse(raw_json)


def validate_payload(
    value: Any,
    references: IncidentReferenceCatalog,
) -> IncidentPayload:
    """Convenience entry point for an already-decoded direct JSON body."""

    return IncidentPayloadParser(references).validate(value)


def parse_uploaded_payload(
    *,
    filename: str,
    content: bytes,
    references: IncidentReferenceCatalog,
) -> IncidentPayload:
    """Convenience entry point for a named uploaded JSON document."""

    return IncidentPayloadParser(references).parse_upload(
        filename=filename,
        content=content,
    )


def _validated_reference_ids(values: Iterable[str], name: str) -> frozenset[str]:
    try:
        identifiers = frozenset(values)
    except TypeError as exc:
        raise TypeError(f"{name} must be an iterable of strings") from exc
    if any(
        not isinstance(identifier, str)
        or not identifier
        or identifier != identifier.strip()
        for identifier in identifiers
    ):
        raise ValueError(f"{name} contains an invalid identifier")
    return identifiers


def _decode_json_text(raw_json: str | bytes | bytearray) -> str:
    if isinstance(raw_json, str):
        return raw_json
    if isinstance(raw_json, (bytes, bytearray)):
        try:
            return bytes(raw_json).decode("utf-8")
        except UnicodeDecodeError:
            raise _single_error(
                code="INCIDENT_JSON_ENCODING_INVALID",
                message="JSON 內容必須使用 UTF-8 編碼",
                path="$",
                detail_code="utf8",
                detail_message="JSON 內容不是有效的 UTF-8",
            ) from None
    raise TypeError("raw_json must be str or bytes")


def _extract_records(value: Any) -> list[Any]:
    if isinstance(value, list):
        records = value
    elif isinstance(value, Mapping):
        if set(value) != {"incidents"}:
            raise _single_error(
                code="INCIDENT_PAYLOAD_SHAPE_INVALID",
                message="事件文件頂層結構無效",
                path="$",
                detail_code="top_level_shape",
                detail_message="頂層物件只能包含 incidents 陣列",
            )
        records = value["incidents"]
        if not isinstance(records, list):
            raise _single_error(
                code="INCIDENT_PAYLOAD_SHAPE_INVALID",
                message="事件文件頂層結構無效",
                path="incidents",
                detail_code="array_type",
                detail_message="incidents 必須是陣列",
            )
    else:
        raise _single_error(
            code="INCIDENT_PAYLOAD_SHAPE_INVALID",
            message="事件文件頂層結構無效",
            path="$",
            detail_code="top_level_shape",
            detail_message="頂層必須是事件陣列或只含 incidents 的物件",
        )

    if not records:
        raise _single_error(
            code="INCIDENT_PAYLOAD_EMPTY",
            message="至少需要一筆事件",
            path="incidents",
            detail_code="min_items",
            detail_message="事件陣列至少需要一筆事件",
        )
    if len(records) > MAX_INCIDENT_RECORDS:
        raise _single_error(
            code="INCIDENT_PAYLOAD_TOO_MANY_RECORDS",
            message="事件筆數超過 100 筆上限",
            path="incidents",
            detail_code="max_items",
            detail_message="事件陣列最多接受 100 筆事件",
        )
    return records


def _raw_validation_errors(candidate: Mapping[str, Any]) -> list[tuple[tuple[Any, ...], str, str]]:
    try:
        _IncidentRecordInput.model_validate(candidate)
    except ValidationError as exc:
        return [
            (tuple(error["loc"]), str(error["type"]), str(error["msg"]))
            for error in exc.errors(include_url=False, include_context=False, include_input=False)
        ]
    return []


def _record_field_errors(
    candidate: Mapping[str, Any], index: int
) -> list[ApiErrorDetail]:
    details: list[ApiErrorDetail] = []
    for location, error_type, _ in _raw_validation_errors(candidate):
        field = _first_location_part(location)
        path = _format_record_path(index, location)
        code, message = _safe_field_error(field, error_type)
        details.append(ApiErrorDetail(path=path, code=code, message=message))
    return details


def _safe_field_error(field: str, error_type: str) -> tuple[str, str]:
    if error_type == "missing":
        return "required", f"{field} 為必填欄位"
    if error_type == "extra_forbidden":
        return "extra_field", f"不允許未知欄位 {field}"
    if error_type in {"string_type", "enum"}:
        if field == "severity" and error_type == "enum":
            return "enum", "severity 僅接受 Critical、High、Medium"
        return "type", f"{field} 欄位型別無效"
    if error_type in {"string_too_short", "string_too_long"}:
        return "length", f"{field} 欄位長度無效"
    if field == "timestamp":
        return "datetime", "timestamp 必須是 UTC+8 真實曆法 YYYY-MM-DD HH:MM"
    return "invalid", f"{field} 欄位無效"


def _validate_status(
    *, index: int, category: EventCategory, status: Any
) -> list[ApiErrorDetail]:
    if category is not EventCategory.ROAD_DISRUPTION:
        return []
    normalized_status = status.strip() if isinstance(status, str) else status
    if normalized_status in {"Closed", "Blocked", "Restricted"}:
        return []
    return [
        ApiErrorDetail(
            path=f"incidents[{index}].status",
            code="road_status_invalid",
            message="Road_Disruption status 僅接受 Closed、Blocked、Restricted",
        )
    ]


def _format_record_path(index: int, location: tuple[Any, ...]) -> str:
    path = f"incidents[{index}]"
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def _first_location_part(location: tuple[Any, ...]) -> str:
    return str(location[0]) if location else "$"


def _normalized_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant: {value}")


def _single_error(
    *,
    code: str,
    message: str,
    path: str,
    detail_code: str,
    detail_message: str,
) -> IncidentPayloadValidationError:
    return IncidentPayloadValidationError(
        code=code,
        message=message,
        details=(
            ApiErrorDetail(
                path=path,
                code=detail_code,
                message=detail_message,
            ),
        ),
    )


__all__ = [
    "IncidentPayloadParser",
    "IncidentPayloadValidationError",
    "IncidentReferenceCatalog",
    "MAX_INCIDENT_RECORDS",
    "MAX_UPLOAD_BYTES",
    "MIN_UPLOAD_BYTES",
    "canonical_json_bytes",
    "canonical_sha256",
    "parse_payload",
    "parse_uploaded_payload",
    "validate_payload",
]
