"""Stateless monitoring domain service used by native Lambda handlers.

No symbol is imported from ``backend.main``.  Existing deterministic policy and
traffic calculations are reused under an explicit request-time override obtained
from the DynamoDB-authoritative serverless clock.
"""

from __future__ import annotations

import contextlib
import email.utils
import ipaddress
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from backend import sim_clock
from backend.agents import policy, sop_rules, traffic_math
from backend.data_source import data_source_status, get_data_path

from . import clock

logger = logging.getLogger(__name__)
APP_VERSION = "3.0.0"
_CAMERA_TIMEOUT_SECONDS = min(
    8.0, max(0.5, float(os.environ.get("CAMERA_LAMBDA_TIMEOUT_SECONDS", "3")))
)
_MAX_FRAME_BYTES = 4 * 1024 * 1024
_STALE_AFTER_SECONDS = 180.0
_CAMERA_MAP: dict[str, Any] | None = None


class MonitoringNotFound(LookupError):
    """A requested monitoring resource does not exist."""


class CameraUpstreamError(RuntimeError):
    """A whitelisted camera upstream could not complete a short request."""


def resolve_time(value: object = None) -> str:
    """Resolve every request to one explicit timestamp before domain calls."""

    return clock.resolve(value)


def _clock_for_request(explicit: str, overridden: bool) -> dict[str, Any]:
    projection = clock.state()
    projection["sim_time"] = explicit
    projection["sim_time_iso"] = clock.parse_time(explicit).isoformat()
    stamps = clock.timeline()
    projection["timeline_index"] = max(
        (index for index, stamp in enumerate(stamps) if stamp <= explicit),
        default=None,
    )
    if overridden:
        projection["mode"] = "override"
        projection["is_overridden"] = True
    return projection


def health() -> dict[str, Any]:
    """Return a cheap health payload; this function never probes Bedrock."""

    explicit = resolve_time()
    with sim_clock.override(explicit):
        from backend.agents.architect import bedrock_settings

        state = clock.state()
        return {
            "status": "ok",
            "service": "city-commander-agent",
            "version": APP_VERSION,
            "timestamp": datetime.now().strftime(clock.TIME_FMT),
            "sim_time": explicit,
            "clock_mode": state["mode"],
            "data_mode": os.environ.get("SIM_DATA_MODE", "interpolate"),
            "data_source": data_source_status(),
            "bedrock": bedrock_settings(),
        }


def sop(section: str | None = None) -> dict[str, Any]:
    explicit = resolve_time()
    with sim_clock.override(explicit):
        if section:
            return policy.read_traffic_sop(section)
        data = policy.read_traffic_sop()
        clauses = policy.parse_clauses(data.get("sop_text", ""))
        return {
            "source": data.get("source", "local"),
            "total": len(clauses),
            "thresholds": sop_rules.thresholds_payload(),
            "clauses": [clauses[number] for number in sorted(clauses)],
        }


def _auto_advisory_for(segment: Mapping[str, Any], ts_str: str) -> dict[str, Any]:
    seg_id = str(segment["segment_id"])
    level = str(segment["level"])
    severity = "Critical" if level == "A" else "High"
    advisory: dict[str, Any] = {
        "segment_id": seg_id,
        "road_name": segment["road_name"],
        "level": level,
        "level_description": sop_rules.level_description(level),
        "saturation_score": segment["saturation_score"],
        "is_trigger_segment": True,
        "triggered_by": (
            f"{segment['road_name']} 達 {sop_rules.level_description(level)}"
            f"（飽和度 {round(float(segment['saturation_score']) * 100)}%、"
            f"時速 {segment['avg_speed']} 公里）"
        ),
        "sop_reference": (
            "SOP 第 1 條：觸發路段達 A 級 → 長綠燈時制並同步觸發第 2 條替代路徑引導"
            if level == "A"
            else "SOP 第 1 條：觸發路段達 B 級 → 長綠燈時制並調度警力淨空路口"
        ),
    }
    route: dict[str, Any] | None = None
    if level == "A":
        route = traffic_math.calculate_optimal_route(seg_id, ts_str) or {}
        primary = route.get("primary_route")
        if isinstance(primary, Mapping):
            advisory.update(
                {
                    "primary_route": primary.get("name", ""),
                    "primary_route_id": primary.get("segment_id", ""),
                    "primary_saturation": primary.get("saturation_score"),
                    "selection_reason": route.get("selection_reason", ""),
                    "selection_tier": route.get("selection_tier"),
                    "secondary_routes": [
                        {
                            "name": candidate.get("name", ""),
                            "saturation_score": candidate.get("saturation_score"),
                        }
                        for candidate in route.get("secondary_routes", [])
                        if isinstance(candidate, Mapping)
                    ],
                    "excluded_routes": [
                        {
                            "name": candidate.get("name", ""),
                            "reason": candidate.get("reason", ""),
                        }
                        for candidate in route.get("excluded_routes", [])
                        if isinstance(candidate, Mapping)
                    ],
                    "upstream_resolution": route.get("upstream_resolution", {}),
                    "route_candidates": route.get("all_candidates", []),
                }
            )
    affected_ids = traffic_math.affected_segments_for_ete(seg_id, route)
    ete_data = traffic_math.calculate_ete(severity, affected_ids, ts_str)
    if ete_data and "ete_minutes" in ete_data:
        advisory["ete_minutes"] = ete_data["ete_minutes"]
        advisory["ete_breakdown"] = {
            "severity": ete_data["severity"],
            "severity_basis": (
                "無事故通報，依 SOP 第 1 條分級換算嚴重度："
                f"{level} 級視同 {severity}"
            ),
            "base_clearance_minutes": ete_data["base_clearance_minutes"],
            "congestion_penalty_minutes": ete_data["congestion_penalty_minutes"],
            "avg_saturation_score": ete_data["avg_saturation_score"],
            "affected_segment_ids": ete_data["affected_segment_ids"],
            "formula": ete_data["formula"],
        }
    plan = traffic_math.build_signal_plan(
        seg_id,
        ts_str,
        advisory.get("ete_minutes"),
        str(advisory.get("primary_route_id", "")),
        scope=traffic_math.SIGNAL_SCOPE_SOP1,
    )
    if plan and "error" not in plan:
        advisory["signal_plan"] = plan
        advisory["signal_action"] = "、".join(
            f"{action['road_name']} {action['action']}"
            for action in plan.get("adjustments", [])
        )
        advisory["police_dispatch"] = plan.get("police_dispatch")
        advisory["window"] = plan.get("window", "")
    return advisory


def status(ts: object = None) -> dict[str, Any]:
    import pandas as pd

    from backend.agents.policy import evaluate_data_triggers
    from backend.agents.traffic_math import _get_time_slice, _load_traffic_flow, crowd_snapshot

    explicit = resolve_time(ts)
    overridden = ts is not None and str(ts).strip() != ""
    with sim_clock.override(explicit):
        latest, _ = _get_time_slice(
            _load_traffic_flow(), explicit, key_col="Segment_ID"
        )
        segments: list[dict[str, Any]] = []
        for _, row in latest.iterrows():
            score = round(float(row["Saturation_Score"]), 4)
            level = sop_rules.assess_congestion_level(score)
            weight = float(row.get("Interp_Weight", 0.0) or 0.0)
            segments.append(
                {
                    "segment_id": row["Segment_ID"],
                    "road_name": row["Road_Name"],
                    "saturation_score": score,
                    "avg_speed": round(float(row["Avg_Speed"]), 1),
                    "vehicle_count": int(round(float(row["Vehicle_Count"]))),
                    "lane_status": row["Lane_Status"],
                    "lane_status_label": sop_rules.lane_status_label(row["Lane_Status"]),
                    "level": level,
                    "level_description": sop_rules.level_description(level),
                    "is_trigger_segment": sop_rules.is_trigger_segment(row["Segment_ID"]),
                    "data_as_of": pd.Timestamp(row["Timestamp"]).strftime(clock.TIME_FMT),
                    "is_interpolated": weight > 0,
                    "interp_weight": round(weight, 3),
                }
            )
        segments.sort(key=lambda item: str(item["segment_id"]))
        abnormal = [item for item in segments if item["level"] in {"A", "B"}]

        auto_advisories: list[dict[str, Any]] = []
        for segment in abnormal:
            if not segment["is_trigger_segment"]:
                continue
            try:
                auto_advisories.append(_auto_advisory_for(segment, explicit))
            except Exception as exc:
                logger.warning(
                    "Auto advisory failed for %s: %s",
                    segment["segment_id"],
                    type(exc).__name__,
                )
        auto_advisories.sort(
            key=lambda item: (item["level"] != "A", -float(item["saturation_score"]))
        )
        monitored_alerts = [
            {
                "segment_id": segment["segment_id"],
                "road_name": segment["road_name"],
                "level": segment["level"],
                "level_description": segment["level_description"],
                "saturation_score": segment["saturation_score"],
                "avg_speed": segment["avg_speed"],
                "note": "非 SOP 第 1 條城市應變觸發路段，僅供燈號顯示與監控",
            }
            for segment in abnormal
            if not segment["is_trigger_segment"]
        ]
        data_as_of = max(
            (str(segment["data_as_of"]) for segment in segments), default=None
        )

        stations: list[dict[str, Any]] = []
        try:
            snapshot = crowd_snapshot(explicit)
            for station in snapshot["stations"]:
                stations.append(
                    {
                        "bs_id": station["bs_id"],
                        "location_name": station["location_name"],
                        "user_count": station["user_count"],
                        "stay_time_avg": station["stay_time_avg"],
                        "growth_rate": station["growth_rate"],
                        "roaming_user_pct": station["roaming_user_pct"],
                        "roaming_user_pct_display": station[
                            "roaming_user_pct_display"
                        ],
                        "exceeds_sop6_threshold": station[
                            "exceeds_sop6_threshold"
                        ],
                        "data_as_of": station["data_as_of"],
                    }
                )
        except Exception as exc:
            logger.warning("Crowd snapshot failed: %s", type(exc).__name__)

        try:
            triggers = evaluate_data_triggers(explicit)
            data_triggers = {
                "query_timestamp": triggers["query_timestamp"],
                "data_as_of": triggers["data_as_of"],
                "triggered_numbers": triggers["triggered_numbers"],
                "multilingual_required": triggers["multilingual_required"],
                "languages": triggers["languages"],
                "checks": [
                    {
                        "sop_number": check["sop_number"],
                        "sop_title": check["sop_title"],
                        "triggered": check["triggered"],
                        "reason": check["reason"],
                        "evidence": check.get("evidence", {}),
                        "actions": check.get("actions", []),
                    }
                    for check in triggers["checks"]
                ],
                "roaming_trigger_stations": triggers["roaming_scan"][
                    "trigger_stations"
                ],
            }
        except Exception as exc:
            logger.warning("Data trigger evaluation failed: %s", type(exc).__name__)
            data_triggers = {"triggered_numbers": [], "checks": []}

        return {
            "timestamp": explicit,
            "sim_time": explicit,
            "data_as_of": data_as_of,
            "data_mode": os.environ.get("SIM_DATA_MODE", "interpolate"),
            "is_time_override": overridden,
            "clock": _clock_for_request(explicit, overridden),
            "thresholds": sop_rules.thresholds_payload(),
            "total_segments": len(segments),
            "segments": segments,
            "stations": stations,
            "auto_advisories": auto_advisories,
            "monitored_alerts": monitored_alerts,
            "data_triggers": data_triggers,
            "has_alert": bool(
                abnormal or data_triggers.get("triggered_numbers")
            ),
        }


def trend(
    ts: object = None,
    *,
    full: bool = False,
    window_minutes: int | None = None,
    include_current: bool = True,
) -> dict[str, Any]:
    import pandas as pd

    from backend.agents.traffic_math import _get_time_slice, _load_traffic_flow

    explicit = resolve_time(ts)
    current = pd.Timestamp(clock.parse_time(explicit))
    with sim_clock.override(explicit):
        full_df = _load_traffic_flow()
        frame = full_df
        if not full:
            frame = frame[frame["Timestamp"] <= current]
            if window_minutes is not None:
                frame = frame[
                    frame["Timestamp"]
                    >= current - pd.Timedelta(minutes=int(window_minutes))
                ]
        if frame.empty:
            return {
                "data": [],
                "sim_time": explicit,
                "segments": [],
                "truncated_to_sim_time": not full,
            }
        all_segments = sorted(frame["Segment_ID"].unique().tolist())
        pivot = (
            frame.pivot_table(
                index="Timestamp",
                columns="Segment_ID",
                values="Saturation_Score",
                aggfunc="first",
            )
            .reset_index()
            .sort_values("Timestamp")
        )
        points: list[dict[str, Any]] = []
        for _, row in pivot.iterrows():
            stamp = row["Timestamp"].strftime(clock.TIME_FMT)
            point: dict[str, Any] = {
                "time": stamp,
                "timestamp": stamp,
                "is_current": False,
            }
            for segment in all_segments:
                value = row.get(segment)
                point[segment] = round(float(value), 3) if pd.notna(value) else None
            points.append(point)
        if not full and include_current:
            current_slice, _ = _get_time_slice(
                full_df, explicit, key_col="Segment_ID"
            )
            if not points or points[-1]["timestamp"] != explicit:
                point = {
                    "time": explicit,
                    "timestamp": explicit,
                    "is_current": True,
                    **{segment: None for segment in all_segments},
                }
                for _, row in current_slice.iterrows():
                    segment = row["Segment_ID"]
                    if segment in point:
                        point[segment] = round(float(row["Saturation_Score"]), 3)
                points.append(point)
        return {
            "data": points,
            "sim_time": explicit,
            "segments": all_segments,
            "truncated_to_sim_time": not full,
        }


def network() -> dict[str, Any]:
    explicit = resolve_time()
    with sim_clock.override(explicit):
        path = get_data_path("road_network_geometry.json")
        if not path.exists():
            return {"segments": []}
        with Path(path).open(encoding="utf-8") as source:
            segments = json.load(source)
        return {"total_segments": len(segments), "segments": segments}


def timeline_state() -> dict[str, Any]:
    stamps = clock.timeline()
    current_state = clock.state()
    return {
        "total": len(stamps),
        "timestamps": stamps,
        "current_index": current_state["timeline_index"],
        "current": current_state["sim_time"],
    }


def _load_camera_map() -> dict[str, Any]:
    global _CAMERA_MAP
    if _CAMERA_MAP is None:
        path = get_data_path("segment_cameras.json")
        if not path.exists():
            _CAMERA_MAP = {"segments": {}}
        else:
            with Path(path).open(encoding="utf-8") as source:
                loaded = json.load(source)
            _CAMERA_MAP = loaded if isinstance(loaded, dict) else {"segments": {}}
    return _CAMERA_MAP


def _camera_source(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": data.get("source", ""),
        "source_page": data.get("source_page", ""),
        "stream_source": data.get("stream_source", ""),
        "generated_at": data.get("generated_at", ""),
    }


def cameras() -> dict[str, Any]:
    data = _load_camera_map()
    segments = data.get("segments") or {}
    return {
        **_camera_source(data),
        "max_distance_m": data.get("max_distance_m"),
        "total_segments": len(segments),
        "segments": segments,
    }


def segment_cameras(segment_id: str) -> dict[str, Any]:
    data = _load_camera_map()
    entry = (data.get("segments") or {}).get(segment_id)
    if not isinstance(entry, Mapping):
        raise MonitoringNotFound(f"路段 {segment_id} 無攝影機對照資料")
    camera_list = entry.get("cameras") or []
    return {
        "segment_id": segment_id,
        "road_name": entry.get("road_name", ""),
        **_camera_source(data),
        "total": len(camera_list),
        "cameras": camera_list,
    }


def _find_camera(segment_id: str, camera_id: str) -> dict[str, Any]:
    entry = (_load_camera_map().get("segments") or {}).get(segment_id)
    if isinstance(entry, Mapping):
        for camera in entry.get("cameras") or []:
            if isinstance(camera, Mapping) and camera.get("camera_id") == camera_id:
                return dict(camera)
    raise MonitoringNotFound(f"路段 {segment_id} 無鏡頭 {camera_id}")


def _allowed_camera_host(hostname: str) -> bool:
    host = hostname.rstrip(".").casefold()
    configured = {
        item.strip().casefold().rstrip(".")
        for item in (os.environ.get("CAMERA_ALLOWED_HOSTS") or "").split(",")
        if item.strip()
    }
    if configured:
        return host in configured
    return host == "c01.twipcam.com" or host.endswith(".gov.taipei")


def _whitelisted_url(camera: Mapping[str, Any], field: str) -> str:
    value = camera.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CameraUpstreamError("攝影機未提供可用的上游網址")
    url = value.strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not _allowed_camera_host(parsed.hostname)
    ):
        raise CameraUpstreamError("攝影機上游網址未通過白名單")
    with contextlib.suppress(ValueError):
        address = ipaddress.ip_address(parsed.hostname)
        if not address.is_global:
            raise CameraUpstreamError("攝影機上游網址不可指向內部網路")
    return url


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _open_camera(request: urllib.request.Request):
    opener = urllib.request.build_opener(_RejectRedirects())
    return opener.open(request, timeout=_CAMERA_TIMEOUT_SECONDS)


def camera_snapshot(segment_id: str, camera_id: str) -> tuple[bytes, str]:
    camera = _find_camera(segment_id, camera_id)
    url = _whitelisted_url(camera, "snapshot_url")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "city-commander-lambda/1.0", "Accept": "image/*"},
    )
    try:
        with _open_camera(request) as response:
            content_type = (
                response.headers.get("Content-Type") or "image/jpeg"
            ).split(";", 1)[0].strip()
            if not content_type.casefold().startswith("image/"):
                raise CameraUpstreamError("上游回傳非影像內容")
            body = response.read(_MAX_FRAME_BYTES + 1)
    except CameraUpstreamError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        raise CameraUpstreamError("影像目前無法取得") from exc
    if not body:
        raise CameraUpstreamError("上游回傳空影像")
    if len(body) > _MAX_FRAME_BYTES:
        raise CameraUpstreamError("上游影像超過大小上限")
    return body, content_type


def camera_stream_url(segment_id: str, camera_id: str) -> str:
    camera = _find_camera(segment_id, camera_id)
    return _whitelisted_url(camera, "stream_url")


def _frame_headers(url: str) -> tuple[Mapping[str, str], int | None]:
    headers = {"User-Agent": "city-commander-lambda/1.0", "Accept": "image/*"}
    head = urllib.request.Request(url, method="HEAD", headers=headers)
    try:
        with _open_camera(head) as response:
            return response.headers, None
    except urllib.error.HTTPError as exc:
        if exc.code not in {400, 403, 405, 501}:
            raise
    get = urllib.request.Request(
        url,
        method="GET",
        headers={**headers, "Range": "bytes=0-0"},
    )
    with _open_camera(get) as response:
        response.read(1)
        return response.headers, 1


def camera_frame(segment_id: str, camera_id: str) -> dict[str, Any]:
    camera = _find_camera(segment_id, camera_id)
    url = _whitelisted_url(camera, "snapshot_url")
    fetched_at = datetime.now(timezone.utc)
    base = {
        "segment_id": segment_id,
        "camera_id": camera_id,
        "name": camera.get("name", ""),
        "distance_m": camera.get("distance_m"),
    }
    try:
        headers, fetched_bytes = _frame_headers(url)
        content_type = (headers.get("Content-Type") or "image/jpeg").split(";", 1)[0]
        raw_length = headers.get("Content-Length")
        byte_count = int(raw_length) if raw_length and raw_length.isdigit() else fetched_bytes
        captured_at: datetime | None = None
        raw_modified = headers.get("Last-Modified")
        if raw_modified:
            with contextlib.suppress(TypeError, ValueError):
                captured_at = email.utils.parsedate_to_datetime(raw_modified)
                if captured_at and captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=timezone.utc)
        age = (
            max(0.0, (fetched_at - captured_at.astimezone(timezone.utc)).total_seconds())
            if captured_at
            else None
        )
        return {
            **base,
            "available": content_type.casefold().startswith("image/"),
            "source": "upstream",
            "is_mock": False,
            "content_type": content_type,
            "bytes": byte_count,
            "captured_at": captured_at.isoformat() if captured_at else None,
            "fetched_at": fetched_at.isoformat(),
            "age_seconds": round(age, 2) if age is not None else None,
            "is_stale": age is not None and age > _STALE_AFTER_SECONDS,
            "upstream_error": "",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        logger.warning("Camera frame metadata unavailable: %s", type(exc).__name__)
        return {
            **base,
            "available": False,
            "source": "upstream",
            "is_mock": False,
            "content_type": None,
            "bytes": None,
            "captured_at": None,
            "fetched_at": fetched_at.isoformat(),
            "age_seconds": None,
            "is_stale": None,
            "upstream_error": "影像目前無法取得",
        }


__all__ = [
    "CameraUpstreamError",
    "MonitoringNotFound",
    "camera_frame",
    "camera_snapshot",
    "camera_stream_url",
    "cameras",
    "health",
    "network",
    "resolve_time",
    "segment_cameras",
    "sop",
    "status",
    "timeline_state",
    "trend",
]
