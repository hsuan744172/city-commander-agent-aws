"""API Gateway v2 handler for alert summaries and persistent What-if chat."""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from backend import sim_clock
from backend.agents import architect

from . import clock, monitoring_service
from .http import (
    HTTPError,
    Request,
    invoke,
    json_response,
    method_not_allowed,
    not_found,
)
from .public_payload import sanitize_public
from .repository import get_repository

_SESSION_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _session_id(value: object, *, create: bool) -> str:
    text = str(value or "").strip()
    if not text and create:
        text = f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
    if not _SESSION_ID.fullmatch(text):
        raise HTTPError(
            400,
            "SESSION_ID_INVALID",
            "session_id 格式無效",
            details=[{"path": "session_id", "code": "format"}],
        )
    return text


def _explicit_time(value: object = None) -> str:
    try:
        return clock.resolve(value)
    except ValueError as exc:
        raise HTTPError(
            400,
            "SIM_TIME_INVALID",
            "sim_time 必須使用 YYYY-MM-DD HH:MM 格式",
            details=[{"path": "sim_time", "code": "datetime"}],
        ) from exc


def _alert_summary(request: Request) -> dict[str, Any]:
    explicit = _explicit_time(request.query_value("ts"))
    segment_id = (request.query_value("segment_id") or "").strip()
    status = monitoring_service.status(explicit)
    with sim_clock.override(explicit):
        if segment_id:
            result = architect.generate_segment_alert_summary(
                status, segment_id, explicit
            )
        else:
            result = architect.generate_alert_summary(
                status, status.get("data_triggers"), explicit
            )
    return json_response(sanitize_public(result))


def _what_if(request: Request) -> dict[str, Any]:
    body = request.json_object()
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPError(
            400,
            "WHAT_IF_PROMPT_REQUIRED",
            "prompt 不可為空",
            details=[{"path": "prompt", "code": "required"}],
        )
    if len(prompt) > 8000:
        raise HTTPError(400, "WHAT_IF_PROMPT_TOO_LONG", "prompt 長度不可超過 8000 字")
    session_id = _session_id(body.get("session_id"), create=True)
    explicit = _explicit_time(body.get("sim_time"))
    repository = get_repository()

    # Architect's existing helpers read their module-level session map.  Hydrate
    # it under the module lock, run without holding that non-reentrant lock, then
    # persist the new authoritative history back to DynamoDB.
    history = repository.get_chat(session_id)
    with architect._chat_lock:  # type: ignore[attr-defined]
        if history:
            architect._chat_sessions[session_id] = copy.deepcopy(history)  # type: ignore[attr-defined]
        else:
            architect._chat_sessions.pop(session_id, None)  # type: ignore[attr-defined]

    result = architect.run_what_if(prompt.strip(), session_id, explicit)

    with architect._chat_lock:  # type: ignore[attr-defined]
        updated = copy.deepcopy(  # type: ignore[attr-defined]
            architect._chat_sessions.get(session_id, [])
        )
    if updated:
        repository.put_chat(session_id, updated)
    return json_response(sanitize_public(result))


def _reset(request: Request) -> dict[str, Any]:
    body = request.json_object()
    session_id = _session_id(body.get("session_id"), create=False)
    architect.reset_chat_session(session_id)
    get_repository().delete_chat(session_id)
    return json_response({"status": "reset", "session_id": session_id})


def _dispatch(request: Request) -> dict[str, Any]:
    parts = request.route_parts("advisor")
    if request.method == "GET" and parts == ("alert-summary",):
        return _alert_summary(request)
    if request.method == "POST" and parts == ("what-if",):
        return _what_if(request)
    if request.method == "POST" and parts in {("what-if", "reset"), ("reset",)}:
        return _reset(request)
    if parts == ("alert-summary",):
        return method_not_allowed(request, "GET")
    if parts in {("what-if",), ("what-if", "reset"), ("reset",)}:
        return method_not_allowed(request, "POST")
    return not_found(request)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    return invoke(event, context, _dispatch)


__all__ = ["lambda_handler"]
