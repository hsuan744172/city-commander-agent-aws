"""Asynchronous incident preview, injection, and job HTTP handler."""

from __future__ import annotations

import logging
import os
import secrets
import threading
from typing import Any, Mapping
from uuid import uuid4

from backend import sim_clock
from backend.incident_response import (
    CONTRACT_VERSION,
    DEFAULT_HISTORY_LIMIT,
    TIMEZONE_LABEL,
    ApiErrorResponse,
    EventInjectionService,
    IncidentPayloadValidationError,
    InjectionConfirmationError,
    PreviewMismatchError,
)

from . import clock
from .http import (
    HTTPError,
    Request,
    invoke,
    json_response,
    method_not_allowed,
    not_found,
    require_path_token,
)
from .public_payload import sanitize_public
from .repository import RepositoryError, get_repository, utc_now_iso

logger = logging.getLogger(__name__)
_SERVICE: EventInjectionService | None = None
_SERVICE_LOCK = threading.Lock()
DEADLINE_SECONDS = 60


def _service() -> EventInjectionService:
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = EventInjectionService()
    return _SERVICE


def _json_only(request: Request) -> dict[str, Any]:
    media_type = (request.header("content-type") or "").split(";", 1)[0].strip().casefold()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise HTTPError(
            415,
            "INCIDENT_JSON_REQUIRED",
            "此端點僅接受 application/json",
            details=[{"path": "content-type", "code": "media_type"}],
        )
    return request.json_object()


def _token_denied(request: Request) -> bool:
    expected = (os.environ.get("INCIDENT_INJECT_TOKEN") or "").strip()
    if not expected:
        return False
    supplied = (
        request.header("x-admin-token")
        or request.header("x-incident-inject-token")
        or request.header("incident-inject-token")
        or ""
    )
    return not secrets.compare_digest(supplied, expected)


def _error_payload(exc: Any, request: Request, status_code: int) -> dict[str, Any]:
    envelope = ApiErrorResponse(
        error=exc.as_api_error(trace_id=request.request_id)
    ).model_dump(mode="json")
    return json_response(envelope, status_code)


def _internal_error(request: Request, code: str = "INCIDENT_INTERNAL_ERROR") -> dict[str, Any]:
    envelope = ApiErrorResponse.internal(
        code=code, trace_id=request.request_id
    ).model_dump(mode="json")
    return json_response(envelope, 500)


def _sim_time(value: object = None) -> str:
    try:
        return clock.resolve(value)
    except ValueError as exc:
        raise HTTPError(
            400,
            "INCIDENT_SIM_TIME_INVALID",
            "模擬時間格式無效",
            details=[
                {
                    "path": "sim_time",
                    "code": "datetime",
                    "message": "請使用 UTC+8 的 YYYY-MM-DD HH:MM 格式",
                }
            ],
        ) from exc


def _preview_response(preview: Any) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "timezone": TIMEZONE_LABEL,
        "preview": preview.model_dump(mode="json"),
    }


def _agent_incident(record: Any) -> dict[str, Any]:
    value = record.model_dump(mode="json")
    value.pop("category", None)
    value.pop("original_index", None)
    return {key: item for key, item in value.items() if item is not None}


def _catalog(request: Request) -> dict[str, Any]:
    explicit = _sim_time()
    refresh = request.query_bool("refresh", False)
    with sim_clock.override(explicit):
        catalog = _service().catalog(refresh=refresh)
    return json_response(
        {
            "contract_version": CONTRACT_VERSION,
            "timezone": TIMEZONE_LABEL,
            "sim_time": explicit,
            "requires_admin_token": bool(
                (os.environ.get("INCIDENT_INJECT_TOKEN") or "").strip()
            ),
            **catalog.as_api_dict(),
        }
    )


def _preview(request: Request) -> dict[str, Any]:
    body = _json_only(request)
    explicit = _sim_time(body.get("sim_time"))
    try:
        with sim_clock.override(explicit):
            preview = _service().preview_json(
                body.get("payload"), simulation_clock_time=explicit
            )
    except IncidentPayloadValidationError as exc:
        return _error_payload(exc, request, 400)
    return json_response(_preview_response(preview))


def _inject(request: Request) -> dict[str, Any]:
    if _token_denied(request):
        return json_response(
            {
                "contract_version": CONTRACT_VERSION,
                "timezone": TIMEZONE_LABEL,
                "error": {
                    "code": "INCIDENT_ADMIN_FORBIDDEN",
                    "message": "事件注入需要管理員權杖",
                    "trace_id": request.request_id,
                    "details": [
                        {
                            "path": "X-Admin-Token",
                            "code": "admin_token_invalid",
                            "message": "請提供正確權杖",
                        }
                    ],
                },
            },
            403,
        )
    body = _json_only(request)
    explicit = _sim_time(body.get("sim_time"))
    try:
        with sim_clock.override(explicit):
            preview = _service().preview_json(
                body.get("payload"), simulation_clock_time=explicit
            )
        _service().verify_preview_hash(preview, body.get("preview_hash"))
        _service().verify_confirmations(preview, body.get("confirmations"))
    except IncidentPayloadValidationError as exc:
        return _error_payload(exc, request, 400)
    except InjectionConfirmationError as exc:
        return _error_payload(exc, request, 400)
    except PreviewMismatchError as exc:
        return _error_payload(exc, request, 409)

    incidents = [_agent_incident(item) for item in preview.normalized_payload.incidents]
    job_id = f"inj_{uuid4().hex}"
    session_id = str(body.get("session_id") or f"inject_{job_id[4:20]}").strip()
    if not session_id or len(session_id) > 160:
        raise HTTPError(400, "SESSION_ID_INVALID", "session_id 格式無效")
    submitted_at = utc_now_iso()
    request_document = {
        "contract_version": CONTRACT_VERSION,
        "timezone": TIMEZONE_LABEL,
        "job_id": job_id,
        "session_id": session_id,
        "sim_time": explicit,
        "submitted_at": submitted_at,
        "deadline_seconds": DEADLINE_SECONDS,
        "preview": preview.model_dump(mode="json"),
        "incidents": incidents,
    }
    metadata = {
        "status": "queued",
        "job_id": job_id,
        "injection_id": job_id,
        "session_id": session_id,
        "source_label": str(preview.source_label),
        "preview_hash": preview.preview_hash,
        "payload_hash": preview.normalized_payload.normalized_hash,
        "event_ids": [item.event_id for item in preview.normalized_payload.incidents],
        "simulation_clock_time": explicit,
        "deadline_seconds": DEADLINE_SECONDS,
        "submitted_at": submitted_at,
    }
    repository = get_repository()
    try:
        repository.put_job_request(job_id, request_document)
        repository.create_job(job_id, metadata)
        message_id = repository.enqueue_job(job_id)
        try:
            repository.update_job(job_id, queue_message_id=message_id)
        except RepositoryError:
            logger.exception("Unable to record queue message id for job %s", job_id)
    except Exception:
        logger.exception("Unable to enqueue incident job %s", job_id)
        with contextlib.suppress(Exception):
            if repository.get_job(job_id):
                repository.update_job(job_id, status="failed", failure_code="enqueue_failed")
        return _internal_error(request, "INCIDENT_ENQUEUE_FAILED")

    return json_response(
        {
            "job_id": job_id,
            "status": "queued",
            "status_url": f"/api/incidents/jobs/{job_id}",
            "submitted_at": submitted_at,
            "deadline_seconds": DEADLINE_SECONDS,
        },
        202,
    )


def _job(request: Request, job_id: str) -> dict[str, Any]:
    repository = get_repository()
    metadata = repository.get_job(job_id)
    if metadata is None:
        raise HTTPError(404, "INCIDENT_JOB_NOT_FOUND", "找不到指定的事件工作")
    result = dict(metadata)
    report = repository.get_job_result(job_id)
    if report is not None:
        result["report"] = sanitize_public(report)
    return json_response(result)


def _injections(request: Request) -> dict[str, Any]:
    limit = request.query_int(
        "limit", 5, minimum=1, maximum=DEFAULT_HISTORY_LIMIT
    )
    include_report = request.query_bool("include_report", False)
    repository = get_repository()
    records: list[dict[str, Any]] = []
    for item in repository.list_jobs(limit=limit):
        projected = dict(item)
        if include_report:
            report = repository.get_job_result(str(item.get("job_id") or ""))
            if report is not None:
                projected["report"] = sanitize_public(report)
        records.append(projected)
    return json_response(
        {
            "contract_version": CONTRACT_VERSION,
            "timezone": TIMEZONE_LABEL,
            "count": len(records),
            "injections": records,
        }
    )


def _dispatch(request: Request) -> dict[str, Any]:
    parts = request.route_parts("incidents", "incident")
    if request.method == "GET" and parts == ("catalog",):
        return _catalog(request)
    if request.method == "POST" and parts == ("preview",):
        return _preview(request)
    if request.method == "POST" and parts == ("inject",):
        return _inject(request)
    if request.method == "GET" and len(parts) == 2 and parts[0] == "jobs":
        return _job(request, require_path_token(parts[1], "job_id"))
    if request.method == "GET" and parts == ("injections",):
        return _injections(request)
    if parts in {("catalog",), ("injections",)} or (
        len(parts) == 2 and parts[0] == "jobs"
    ):
        return method_not_allowed(request, "GET")
    if parts in {("preview",), ("inject",)}:
        return method_not_allowed(request, "POST")
    return not_found(request)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    return invoke(event, context, _dispatch)


# Imported late only to keep the public import section focused on domain APIs.
import contextlib  # noqa: E402

__all__ = ["lambda_handler"]
