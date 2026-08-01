"""Strict, immutable domain contracts for incident response API v1.

The models in this module contain no I/O or orchestration logic.  They form the
stable boundary shared by parsers, the deterministic engine, stores, and API
projection code.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Final, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_serializer,
    field_validator,
    model_validator,
)

from .config import CONTRACT_VERSION

UTC_PLUS_8: Final[timezone] = timezone(timedelta(hours=8))
TIMEZONE_LABEL: Final[str] = "UTC+08:00"
LOCAL_DATETIME_FORMAT: Final[str] = "%Y-%m-%d %H:%M"


def parse_utc8_datetime(value: str) -> datetime:
    """Parse an exact, real-calendar ``YYYY-MM-DD HH:MM`` UTC+8 timestamp."""

    if not isinstance(value, str):
        raise TypeError("timestamp must be a string")
    if len(value) != 16:
        raise ValueError("timestamp must use YYYY-MM-DD HH:MM")
    try:
        parsed = datetime.strptime(value, LOCAL_DATETIME_FORMAT)
    except ValueError as exc:
        raise ValueError("timestamp must be a real UTC+8 date and time") from exc
    if parsed.strftime(LOCAL_DATETIME_FORMAT) != value:
        raise ValueError("timestamp must use YYYY-MM-DD HH:MM")
    return parsed.replace(tzinfo=UTC_PLUS_8)


def project_utc8_datetime(value: datetime) -> str:
    """Project an aware datetime to the API's offsetless UTC+8 representation."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC_PLUS_8).strftime(LOCAL_DATETIME_FORMAT)


def _require_aware_datetime(value: Any) -> Any:
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


Utc8DateTime = Annotated[
    datetime,
    BeforeValidator(_require_aware_datetime),
    PlainSerializer(project_utc8_datetime, return_type=str, when_used="json"),
]


def _trim_string(value: Any) -> Any:
    # Trimming is required normalization, not type coercion. Non-strings are
    # returned unchanged so Pydantic strict validation reports their real type.
    return value.strip() if isinstance(value, str) else value


def _validate_incident_timestamp(value: str) -> str:
    parse_utc8_datetime(value)
    return value


TrimmedString64 = Annotated[
    str, BeforeValidator(_trim_string), Field(min_length=1, max_length=64)
]
TrimmedString120 = Annotated[
    str, BeforeValidator(_trim_string), Field(min_length=1, max_length=120)
]
TrimmedString160 = Annotated[
    str, BeforeValidator(_trim_string), Field(min_length=1, max_length=160)
]
TrimmedString500 = Annotated[
    str, BeforeValidator(_trim_string), Field(min_length=1, max_length=500)
]
IncidentTimestamp = Annotated[str, AfterValidator(_validate_incident_timestamp)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
StableErrorCode = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]


class SourceLabel(StrEnum):
    TIME_SERIES_ALERT = "time_series_alert"
    JSON_UPLOAD = "json_upload"
    MONITORING_PROMOTION = "monitoring_promotion"


class Severity(StrEnum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"


class EventCategory(StrEnum):
    ROAD_DISRUPTION = "Road_Disruption"
    CROWD_SURGE = "Crowd_Surge"
    SIGNAL_FAILURE = "Signal_Failure"


class RoadIncidentStatus(StrEnum):
    CLOSED = "Closed"
    BLOCKED = "Blocked"
    RESTRICTED = "Restricted"


class RunStatus(StrEnum):
    ACCEPTED = "accepted"
    VALIDATING = "validating"
    ASSESSING = "assessing"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    COMPLETED_WITH_FALLBACK = "completed_with_fallback"
    COMPLETED_WITH_PARTIAL_FAILURE = "completed_with_partial_failure"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_RUN_STATUSES


TERMINAL_RUN_STATUSES: Final[frozenset[RunStatus]] = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_FALLBACK,
        RunStatus.COMPLETED_WITH_PARTIAL_FAILURE,
        RunStatus.FAILED,
    }
)


class FallbackReason(StrEnum):
    TIMEOUT = "timeout"
    SERVICE_ERROR = "service_error"
    CONSISTENCY_FAILURE = "consistency_failure"
    GLOBAL_DEADLINE = "global_deadline"


class SourceAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class SopDecisionStatus(StrEnum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    INDETERMINATE = "indeterminate"


class RoutePlanStatus(StrEnum):
    PLANNED = "planned"
    UNPLANNABLE = "unplannable"
    NOT_APPLICABLE = "not_applicable"


class IntersectionRelation(StrEnum):
    TRUE = "true"
    FALSE = "false"
    INDETERMINATE = "indeterminate"


class RouteDirection(StrEnum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    INDETERMINATE = "indeterminate"


class RouteEligibility(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    EXCLUDED = "excluded"


class EteStatus(StrEnum):
    CALCULATED = "calculated"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class ActionStatus(StrEnum):
    RECOMMENDED = "recommended"
    NOT_RECOMMENDED = "not_recommended"


class CmsStatus(StrEnum):
    PUBLISHABLE = "publishable"
    NOT_PUBLISHABLE = "not_publishable"


class CmsLanguage(StrEnum):
    TRADITIONAL_CHINESE = "zh-TW"
    ENGLISH = "en"
    JAPANESE = "ja"
    KOREAN = "ko"


class NarrativeMode(StrEnum):
    AI = "ai"
    FALLBACK = "fallback"


class PublicationMode(StrEnum):
    SIMULATED = "simulated"


class MonitoringAlertLevel(StrEnum):
    B = "B"
    A = "A"


class PreviewConfirmation(StrEnum):
    PAYLOAD = "payload"
    FUTURE_SIMULATION = "future_simulation"


# Enum values are accepted from their exact JSON strings while the enclosing
# model remains strict for all primitive types. Values such as ints/bools are
# never converted to strings or enum members.
def _enum_input(enum_type: type[StrEnum]) -> Any:
    return Annotated[enum_type, Field(strict=False)]


SourceLabelValue = _enum_input(SourceLabel)
SeverityValue = _enum_input(Severity)
EventCategoryValue = _enum_input(EventCategory)
RunStatusValue = _enum_input(RunStatus)
FallbackReasonValue = _enum_input(FallbackReason)
SourceAvailabilityValue = _enum_input(SourceAvailability)
SopDecisionStatusValue = _enum_input(SopDecisionStatus)
RoutePlanStatusValue = _enum_input(RoutePlanStatus)
IntersectionRelationValue = _enum_input(IntersectionRelation)
RouteDirectionValue = _enum_input(RouteDirection)
RouteEligibilityValue = _enum_input(RouteEligibility)
EteStatusValue = _enum_input(EteStatus)
ActionStatusValue = _enum_input(ActionStatus)
CmsStatusValue = _enum_input(CmsStatus)
CmsLanguageValue = _enum_input(CmsLanguage)
NarrativeModeValue = _enum_input(NarrativeMode)
PublicationModeValue = _enum_input(PublicationMode)
MonitoringAlertLevelValue = _enum_input(MonitoringAlertLevel)
PreviewConfirmationValue = _enum_input(PreviewConfirmation)


class FrozenStrictModel(BaseModel):
    """Base for contracts that reject coercion, unknown fields, and mutation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        validate_default=True,
    )


class IncidentRecordV1(FrozenStrictModel):
    event_id: TrimmedString64
    type: TrimmedString64
    location: TrimmedString120
    affected_segment: TrimmedString64
    severity: SeverityValue
    description: TrimmedString500
    timestamp: IncidentTimestamp
    status: TrimmedString64 | None = None
    # Crowd events may additionally block a road (for example an ambulance
    # occupying a lane). Optional, and validated against the road network when
    # present. It never changes the event's category.
    affected_road: TrimmedString64 | None = None
    category: EventCategoryValue
    original_index: int = Field(ge=0)

    @property
    def effective_event_time(self) -> datetime:
        return parse_utc8_datetime(self.timestamp)


class IncidentPayloadV1(FrozenStrictModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    incidents: tuple[IncidentRecordV1, ...] = Field(min_length=1, max_length=100)
    normalized_hash: Sha256Hex


class PreviewEventSummary(FrozenStrictModel):
    original_index: int = Field(ge=0)
    event_id: TrimmedString64
    category: EventCategoryValue
    location: TrimmedString120
    affected_segment: TrimmedString64
    severity: SeverityValue
    timestamp: IncidentTimestamp
    possible_sop_articles: tuple[int, ...] = ()


class IncidentPreview(FrozenStrictModel):
    preview_id: TrimmedString64
    preview_hash: Sha256Hex
    source_label: SourceLabelValue
    normalized_payload: IncidentPayloadV1
    event_summaries: tuple[PreviewEventSummary, ...] = Field(min_length=1, max_length=100)
    created_at: Utc8DateTime
    expires_at: Utc8DateTime
    simulation_clock_time: Utc8DateTime
    contains_future_event: bool
    required_confirmations: tuple[PreviewConfirmationValue, ...]

    @model_validator(mode="after")
    def expiration_follows_creation(self) -> IncidentPreview:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return self


class ValidationSummary(FrozenStrictModel):
    valid: bool
    record_count: int = Field(ge=0)
    errors: tuple[str, ...] = ()


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, frozenset)):
        return [_deep_thaw(item) for item in value]
    return value


RecordT = TypeVar("RecordT")


class SourceSnapshot(FrozenStrictModel, Generic[RecordT]):
    requires_actual_data_time: ClassVar[bool] = True

    source: TrimmedString64
    schema_version: TrimmedString64
    content_hash: Sha256Hex
    requested_as_of: Utc8DateTime
    actual_data_time: Utc8DateTime | None = None
    availability: SourceAvailabilityValue
    unavailable_reason: TrimmedString500 | None = None
    records: tuple[RecordT, ...] = ()
    validation_summary: ValidationSummary

    @model_validator(mode="after")
    def availability_is_consistent(self) -> SourceSnapshot[RecordT]:
        if self.availability is SourceAvailability.AVAILABLE:
            if self.requires_actual_data_time and self.actual_data_time is None:
                raise ValueError("available source requires actual_data_time")
            if self.unavailable_reason is not None:
                raise ValueError("available source cannot have unavailable_reason")
            if (
                self.actual_data_time is not None
                and self.actual_data_time > self.requested_as_of
            ):
                raise ValueError("actual_data_time cannot be later than requested_as_of")
        else:
            if self.actual_data_time is not None or self.records:
                raise ValueError("unavailable source cannot expose data records or time")
            if self.unavailable_reason is None:
                raise ValueError("unavailable source requires unavailable_reason")
        return self


class UntypedSourceSnapshot(SourceSnapshot[Mapping[str, Any]]):
    """Immutable snapshot contract used until source-specific records are bound."""

    @field_validator("records", mode="after")
    @classmethod
    def freeze_records(
        cls, value: tuple[Mapping[str, Any], ...]
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(_deep_freeze(record) for record in value)

    @field_serializer("records")
    def serialize_records(self, value: tuple[Mapping[str, Any], ...]) -> list[dict[str, Any]]:
        return [_deep_thaw(record) for record in value]


class StaticSourceSnapshot(UntypedSourceSnapshot):
    requires_actual_data_time: ClassVar[bool] = False
    actual_data_time: None = None

    @model_validator(mode="after")
    def static_availability_is_consistent(self) -> StaticSourceSnapshot:
        if self.availability is SourceAvailability.AVAILABLE:
            if self.unavailable_reason is not None:
                raise ValueError("available static source cannot have unavailable_reason")
        else:
            if self.records:
                raise ValueError("unavailable static source cannot expose records")
            if self.unavailable_reason is None:
                raise ValueError("unavailable static source requires unavailable_reason")
        return self


class SnapshotBundle(FrozenStrictModel):
    effective_event_time: Utc8DateTime
    simulation_clock_time: Utc8DateTime
    traffic: UntypedSourceSnapshot
    crowd: UntypedSourceSnapshot
    road_network: StaticSourceSnapshot
    sop: StaticSourceSnapshot


Scalar = str | int | float | bool


class InputVersion(FrozenStrictModel):
    source: TrimmedString64
    schema_version: TrimmedString64
    content_hash: Sha256Hex


class RuleComparison(FrozenStrictModel):
    field: TrimmedString120
    observed: Scalar | None
    operator: Annotated[str, Field(min_length=1, max_length=16)]
    threshold: Scalar | None
    outcome: bool | None


class SopDecision(FrozenStrictModel):
    sop_version: TrimmedString64
    article: int = Field(ge=1)
    status: SopDecisionStatusValue
    comparisons: tuple[RuleComparison, ...] = ()
    missing_inputs: tuple[TrimmedString120, ...] = ()


class RouteCandidate(FrozenStrictModel):
    source_order: int = Field(ge=0)
    segment_id: TrimmedString64
    name: TrimmedString120
    capacity_vph: float | None = Field(default=None, ge=0)
    directly_intersects: IntersectionRelationValue
    direction: RouteDirectionValue
    saturation: float | None = Field(default=None, ge=0)
    stable_sort_key: tuple[float, str] | None = None
    eligibility: RouteEligibilityValue
    selected: bool
    exclusion_reasons: tuple[TrimmedString120, ...] = ()


class RoutePlan(FrozenStrictModel):
    status: RoutePlanStatusValue
    incident_segment: TrimmedString64
    primary_route: TrimmedString64 | None = None
    secondary_routes: tuple[TrimmedString64, ...] = ()
    congestion_exception: bool = False
    candidates: tuple[RouteCandidate, ...] = ()


class EteResult(FrozenStrictModel):
    status: EteStatusValue
    affected_segments: tuple[TrimmedString64, ...] = ()
    saturation_values: tuple[float, ...] = ()
    arithmetic_mean: float | None = None
    severity: SeverityValue | None = None
    base_clearance_minutes: float | None = Field(default=None, ge=0)
    congestion_penalty_minutes: float | None = Field(default=None, ge=0)
    total_minutes: float | None = Field(default=None, ge=0)
    missing_inputs: tuple[TrimmedString120, ...] = ()


class RecommendedAction(FrozenStrictModel):
    action: TrimmedString64
    status: ActionStatusValue
    target: TrimmedString120 | None = None
    simulated: bool = True


class CmsMessage(FrozenStrictModel):
    language: CmsLanguageValue
    text: TrimmedString160
    char_count: int = Field(ge=1, le=160)
    facts_valid: bool

    @model_validator(mode="after")
    def character_count_matches(self) -> CmsMessage:
        if self.char_count != len(self.text):
            raise ValueError("char_count must equal the Unicode character count")
        return self


class CmsMessageSet(FrozenStrictModel):
    status: CmsStatusValue
    multilingual_triggered: bool
    sop6_status: SopDecisionStatusValue
    messages: tuple[CmsMessage, ...] = ()
    failed_languages: tuple[CmsLanguageValue, ...] = ()


class RequiredResultCheck(FrozenStrictModel):
    complete: bool
    missing_items: tuple[TrimmedString120, ...] = ()


class DeterministicResult(FrozenStrictModel):
    result_schema_version: TrimmedString64
    event_id: TrimmedString64
    category: EventCategoryValue
    effective_event_time: Utc8DateTime
    input_versions: tuple[InputVersion, ...]
    sop_decisions: tuple[SopDecision, ...]
    route_plan: RoutePlan | None
    ete: EteResult
    signal_actions: tuple[RecommendedAction, ...] = ()
    cross_system_actions: tuple[RecommendedAction, ...] = ()
    cms_message_set: CmsMessageSet
    required_result_check: RequiredResultCheck


class TraceTimes(FrozenStrictModel):
    effective_event_time: Utc8DateTime
    simulation_clock_time: Utc8DateTime
    source_actual_times: tuple[tuple[str, Utc8DateTime | None], ...]


class SourceAvailabilityEvidence(FrozenStrictModel):
    source: TrimmedString64
    availability: SourceAvailabilityValue
    actual_data_time: Utc8DateTime | None = None
    reason: TrimmedString500 | None = None


_FORBIDDEN_TRACE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "scratchpad",
        "chainofthought",
        "chain_of_thought",
        "vendordetail",
        "vendor_detail",
    }
)


def _contains_forbidden_trace_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            if normalized in _FORBIDDEN_TRACE_KEYS or _contains_forbidden_trace_key(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_trace_key(child) for child in value)
    return False


class DecisionTrace(FrozenStrictModel):
    trace_schema_version: TrimmedString64
    event_id: TrimmedString64
    times: TraceTimes
    normalized_input_subset: Mapping[str, Any]
    source_availability: tuple[SourceAvailabilityEvidence, ...]
    rules: tuple[SopDecision, ...]
    route_candidates: tuple[RouteCandidate, ...] = ()
    ete_calculation: EteResult | None = None
    selected_actions: tuple[RecommendedAction, ...] = ()
    excluded_options: tuple[TrimmedString120, ...] = ()

    @field_validator("normalized_input_subset", mode="after")
    @classmethod
    def freeze_safe_input_subset(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if _contains_forbidden_trace_key(value):
            raise ValueError("decision trace cannot contain private reasoning or vendor fields")
        return _deep_freeze(value)

    @field_serializer("normalized_input_subset")
    def serialize_input_subset(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _deep_thaw(value)


class NarrativeResult(FrozenStrictModel):
    mode: NarrativeModeValue
    label: Literal["AI 生成說明", "SOP 備援說明"]
    text: TrimmedString500
    validated_claims: tuple[TrimmedString120, ...] = ()
    fallback_reason: FallbackReasonValue | None = None

    @model_validator(mode="after")
    def mode_matches_fallback(self) -> NarrativeResult:
        if self.mode is NarrativeMode.AI:
            if self.label != "AI 生成說明" or self.fallback_reason is not None:
                raise ValueError("AI narrative cannot have a fallback reason")
        elif self.label != "SOP 備援說明" or self.fallback_reason is None:
            raise ValueError("fallback narrative requires a fallback reason")
        return self


class IncidentEventResult(FrozenStrictModel):
    original_index: int = Field(ge=0)
    event_id: TrimmedString64
    succeeded: bool
    deterministic_result: DeterministicResult | None = None
    decision_trace: DecisionTrace | None = None
    narrative: NarrativeResult | None = None
    errors: tuple[TrimmedString500, ...] = ()


class RunStageTimestamp(FrozenStrictModel):
    status: RunStatusValue
    at: Utc8DateTime


class RunStageDuration(FrozenStrictModel):
    status: RunStatusValue
    duration_ms: int = Field(ge=0)


class RunProgress(FrozenStrictModel):
    completed_count: int = Field(ge=0)
    total_count: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def completed_does_not_exceed_total(self) -> RunProgress:
        if self.completed_count > self.total_count:
            raise ValueError("completed_count cannot exceed total_count")
        return self


class MonitoringAlertOrigin(FrozenStrictModel):
    monitoring_alert_id: TrimmedString64
    data_time: Utc8DateTime
    threshold: float = Field(ge=0)
    previous_value: float
    current_value: float


class IncidentRun(FrozenStrictModel):
    run_id: TrimmedString64
    demo_session_id: TrimmedString64
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    source_label: SourceLabelValue
    status: RunStatusValue
    accepted_at: Utc8DateTime
    terminal_at: Utc8DateTime | None = None
    accepted_monotonic: float = Field(ge=0)
    payload_hash: Sha256Hex
    normalized_payload: IncidentPayloadV1
    idempotency_key_hash: Sha256Hex
    simulation_clock_at_accept: Utc8DateTime
    progress: RunProgress
    origin_monitoring_alert: MonitoringAlertOrigin | None = None
    replay_of_run_id: TrimmedString64 | None = None
    snapshot_bundle: SnapshotBundle | None = None
    stage_timestamps: tuple[RunStageTimestamp, ...] = ()
    stage_durations_ms: tuple[RunStageDuration, ...] = ()
    fallback_used: bool = False
    fallback_reasons: tuple[FallbackReasonValue, ...] = ()
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    event_results: tuple[IncidentEventResult, ...] = ()
    missing_required_results: tuple[TrimmedString120, ...] = ()
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def run_summary_is_consistent(self) -> IncidentRun:
        if self.status.is_terminal != (self.terminal_at is not None):
            raise ValueError("terminal_at presence must match terminal status")
        if self.fallback_used != bool(self.fallback_reasons):
            raise ValueError("fallback_used must match fallback_reasons")
        if self.success_count + self.failure_count > self.progress.total_count:
            raise ValueError("result counts cannot exceed total_count")
        if len(self.event_results) > self.progress.total_count:
            raise ValueError("event_results cannot exceed total_count")
        return self


class MonitoringAlert(FrozenStrictModel):
    alert_id: TrimmedString64
    source_label: SourceLabelValue = SourceLabel.TIME_SERIES_ALERT
    segment_id: TrimmedString64
    metric: TrimmedString64
    threshold: float = Field(ge=0)
    level: MonitoringAlertLevelValue
    previous_value: float
    current_value: float
    data_time: Utc8DateTime
    created_at: Utc8DateTime

    @model_validator(mode="after")
    def source_is_time_series(self) -> MonitoringAlert:
        if self.source_label is not SourceLabel.TIME_SERIES_ALERT:
            raise ValueError("monitoring alerts require time_series_alert source")
        return self


class PublicationRecord(FrozenStrictModel):
    publication_id: TrimmedString64
    run_id: TrimmedString64
    message_set_hash: Sha256Hex
    languages: tuple[CmsLanguageValue, ...] = Field(min_length=1)
    messages: tuple[CmsMessage, ...] = Field(min_length=1)
    published_at: Utc8DateTime
    mode: PublicationModeValue = PublicationMode.SIMULATED
    channel_notice: Literal["Simulated_Publish－未連接真實通路"] = (
        "Simulated_Publish－未連接真實通路"
    )

    @model_validator(mode="after")
    def selected_languages_match_messages(self) -> PublicationRecord:
        message_languages = tuple(message.language for message in self.messages)
        if len(set(self.languages)) != len(self.languages):
            raise ValueError("publication languages must be unique")
        if message_languages != self.languages:
            raise ValueError("publication languages and messages must match in order")
        if not all(message.facts_valid for message in self.messages):
            raise ValueError("publication messages must pass facts validation")
        return self


class ApiErrorDetail(FrozenStrictModel):
    path: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    code: Annotated[str, Field(min_length=1, max_length=64)]
    message: TrimmedString500


class ApiError(FrozenStrictModel):
    code: StableErrorCode
    message: TrimmedString500
    trace_id: TrimmedString64
    details: tuple[ApiErrorDetail, ...] = ()


class ApiErrorResponse(FrozenStrictModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    timezone: Literal["UTC+08:00"] = TIMEZONE_LABEL
    error: ApiError

    @classmethod
    def internal(cls, *, code: str, trace_id: str) -> ApiErrorResponse:
        """Build a redacted 5xx-safe envelope without exception/vendor details."""

        return cls(
            error=ApiError(
                code=code,
                message="伺服器暫時無法完成請求",
                trace_id=trace_id,
                details=(),
            )
        )


# Concise aliases are the public domain vocabulary; V1 suffixes remain
# available where callers need explicit versioning.
IncidentRecord = IncidentRecordV1
IncidentPayload = IncidentPayloadV1
Preview = IncidentPreview
Run = IncidentRun


__all__ = [
    "ActionStatus",
    "ApiError",
    "ApiErrorDetail",
    "ApiErrorResponse",
    "CmsLanguage",
    "CmsMessage",
    "CmsMessageSet",
    "CmsStatus",
    "DecisionTrace",
    "DeterministicResult",
    "EteResult",
    "EteStatus",
    "EventCategory",
    "FallbackReason",
    "FrozenStrictModel",
    "IncidentEventResult",
    "IncidentPayload",
    "IncidentPayloadV1",
    "IncidentPreview",
    "IncidentRecord",
    "IncidentRecordV1",
    "IncidentRun",
    "InputVersion",
    "IntersectionRelation",
    "LOCAL_DATETIME_FORMAT",
    "MonitoringAlert",
    "MonitoringAlertLevel",
    "MonitoringAlertOrigin",
    "NarrativeMode",
    "NarrativeResult",
    "Preview",
    "PreviewConfirmation",
    "PreviewEventSummary",
    "PublicationMode",
    "PublicationRecord",
    "RecommendedAction",
    "RequiredResultCheck",
    "RoadIncidentStatus",
    "RouteCandidate",
    "RouteDirection",
    "RouteEligibility",
    "RoutePlan",
    "RoutePlanStatus",
    "RuleComparison",
    "Run",
    "RunProgress",
    "RunStageDuration",
    "RunStageTimestamp",
    "RunStatus",
    "Severity",
    "SnapshotBundle",
    "SopDecision",
    "SopDecisionStatus",
    "SourceAvailability",
    "SourceAvailabilityEvidence",
    "SourceLabel",
    "SourceSnapshot",
    "StaticSourceSnapshot",
    "TERMINAL_RUN_STATUSES",
    "TIMEZONE_LABEL",
    "TraceTimes",
    "UTC_PLUS_8",
    "UntypedSourceSnapshot",
    "Utc8DateTime",
    "ValidationSummary",
    "parse_utc8_datetime",
    "project_utc8_datetime",
]
