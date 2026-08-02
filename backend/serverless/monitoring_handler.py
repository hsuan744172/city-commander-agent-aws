"""API Gateway HTTP API v2 handler for monitoring and clock routes."""

from __future__ import annotations

from typing import Any, Mapping

from . import clock, monitoring_service
from .http import (
    HTTPError,
    Request,
    binary_response,
    invoke,
    json_response,
    method_not_allowed,
    not_found,
    redirect_response,
    require_path_token,
)


def _optional_window(request: Request) -> int | None:
    raw = request.query_value("window_minutes")
    if raw is None or not raw.strip():
        return None
    return request.query_int("window_minutes", 0, minimum=1, maximum=10080)


def _clock_payload() -> dict[str, Any]:
    return {**clock.state(), "modes": list(clock.MODES), "timeline": clock.timeline()}


def _clock_command(function, **kwargs):  # noqa: ANN001
    try:
        return json_response(function(**kwargs))
    except (TypeError, ValueError) as exc:
        raise HTTPError(400, "CLOCK_COMMAND_INVALID", str(exc)) from exc


def _get(request: Request, parts: tuple[str, ...]) -> dict[str, Any]:
    if parts == ("health",):
        return json_response(monitoring_service.health())
    if parts == ("sop",):
        return json_response(monitoring_service.sop(request.query_value("section")))
    if parts == ("status",):
        return json_response(monitoring_service.status(request.query_value("ts")))
    if parts == ("trend",):
        return json_response(
            monitoring_service.trend(
                request.query_value("ts"),
                full=request.query_bool("full", False),
                window_minutes=_optional_window(request),
                include_current=request.query_bool("include_current", True),
            )
        )
    if parts == ("network",):
        return json_response(monitoring_service.network())
    if parts == ("stream",):
        return json_response(clock.live_state())
    if parts == ("timeline",):
        return json_response(monitoring_service.timeline_state())
    if parts == ("clock",):
        return json_response(_clock_payload())
    if parts == ("cameras",):
        return json_response(monitoring_service.cameras())
    if len(parts) == 2 and parts[0] == "cameras":
        segment_id = require_path_token(parts[1], "segment")
        try:
            return json_response(monitoring_service.segment_cameras(segment_id))
        except monitoring_service.MonitoringNotFound as exc:
            raise HTTPError(404, "CAMERA_NOT_FOUND", str(exc)) from exc
    if len(parts) == 4 and parts[0] == "cameras":
        segment_id = require_path_token(parts[1], "segment")
        camera_id = require_path_token(parts[2], "camera")
        operation = parts[3]
        try:
            if operation == "snapshot":
                body, content_type = monitoring_service.camera_snapshot(
                    segment_id, camera_id
                )
                return binary_response(body, content_type, headers={"cache-control": "no-store"})
            if operation == "frame":
                return json_response(
                    monitoring_service.camera_frame(segment_id, camera_id)
                )
            if operation == "stream":
                return redirect_response(
                    monitoring_service.camera_stream_url(segment_id, camera_id), 307
                )
        except monitoring_service.MonitoringNotFound as exc:
            raise HTTPError(404, "CAMERA_NOT_FOUND", str(exc)) from exc
        except monitoring_service.CameraUpstreamError as exc:
            raise HTTPError(502, "CAMERA_UPSTREAM_UNAVAILABLE", str(exc)) from exc
    if parts in {
        ("clock", "advance"),
        ("clock", "pause"),
        ("clock", "resume"),
        ("clock", "reset"),
    }:
        return method_not_allowed(request, "POST")
    return not_found(request)


def _post(request: Request, parts: tuple[str, ...]) -> dict[str, Any]:
    if parts == ("clock",):
        body = request.json_object(required=False)
        return _clock_command(
            clock.configure,
            mode=body.get("mode"),
            sim_time=body.get("sim_time"),
            speed=body.get("speed"),
            interval=body.get("interval"),
            loop=body.get("loop"),
            poll=body.get("poll"),
            paused=body.get("paused"),
        )
    if parts == ("clock", "advance"):
        body = request.json_object()
        return _clock_command(
            clock.advance, minutes=body.get("minutes"), steps=body.get("steps")
        )
    if parts == ("clock", "pause"):
        return _clock_command(clock.pause)
    if parts == ("clock", "resume"):
        return _clock_command(clock.resume)
    if parts == ("clock", "reset"):
        return _clock_command(clock.reset)
    if parts in {
        ("health",),
        ("sop",),
        ("status",),
        ("trend",),
        ("network",),
        ("stream",),
        ("timeline",),
        ("cameras",),
    } or (parts and parts[0] == "cameras"):
        return method_not_allowed(request, "GET")
    return not_found(request)


def _dispatch(request: Request) -> dict[str, Any]:
    parts = request.route_parts("monitoring")
    if request.method == "GET":
        return _get(request, parts)
    if request.method == "POST":
        return _post(request, parts)
    return method_not_allowed(request, "GET, POST")


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    return invoke(event, context, _dispatch)


__all__ = ["lambda_handler"]
