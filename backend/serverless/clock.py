"""DynamoDB-authoritative simulation clock for stateless Lambda handlers.

The process-local clock in :mod:`backend.sim_clock` remains the source of the
validated common data timeline.  Playback state itself is persisted through the
serverless repository so a cold start (or another Lambda execution environment)
continues from the same real/simulation anchors.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from backend import sim_clock

from .repository import get_repository

TIME_FMT = "%Y-%m-%d %H:%M"
MODES = ("live", "playback", "fixed", "latest", "smooth", "auto")
_PLAYING_MODES = frozenset({"live", "playback", "smooth", "auto"})
_DEFAULT_MODE = "live"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _real_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_real(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _parse_real(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return _real_now()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _real_now()
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_time(value: object) -> datetime:
    """Parse the public clock format exactly, rejecting permissive date inputs."""

    if isinstance(value, datetime):
        return value.replace(tzinfo=None, second=0, microsecond=0)
    if not isinstance(value, str):
        raise ValueError("sim_time 必須使用 YYYY-MM-DD HH:MM 格式")
    text = value.strip()
    if len(text) != 16:
        raise ValueError("sim_time 必須使用 YYYY-MM-DD HH:MM 格式")
    try:
        parsed = datetime.strptime(text, TIME_FMT)
    except ValueError as exc:
        raise ValueError("sim_time 必須是有效的 YYYY-MM-DD HH:MM 時間") from exc
    if parsed.strftime(TIME_FMT) != text:
        raise ValueError("sim_time 必須使用 YYYY-MM-DD HH:MM 格式")
    return parsed


def _timeline_values() -> list[datetime]:
    values: list[datetime] = []
    for value in sim_clock.timeline():
        if hasattr(value, "to_pydatetime"):
            parsed = value.to_pydatetime()
        elif isinstance(value, datetime):
            parsed = value
        else:
            parsed = parse_time(str(value)[:16])
        values.append(parsed.replace(tzinfo=None, second=0, microsecond=0))
    return sorted(set(values))


def timeline() -> list[str]:
    """Return the validated common traffic/crowd timeline in public format."""

    return [value.strftime(TIME_FMT) for value in _timeline_values()]


def _default_mode() -> str:
    mode = (os.environ.get("SIM_CLOCK_MODE") or _DEFAULT_MODE).strip().casefold()
    return mode if mode in MODES else _DEFAULT_MODE


def _default_speed(mode: str) -> float:
    if mode == "live":
        return _env_float("SIM_LIVE_SPEED", 1.0)
    return _env_float("SIM_CLOCK_SPEED", 60.0)


def _initial_state(now: datetime | None = None) -> dict[str, Any]:
    real_now = now or _real_now()
    values = _timeline_values()
    mode = _default_mode()
    configured_start = (os.environ.get("SIM_CLOCK_START") or "").strip()
    try:
        start = parse_time(configured_start) if configured_start else None
    except ValueError:
        start = None
    anchor_sim = start or (values[0] if values else real_now.replace(tzinfo=None))
    anchor_sim = _bound(anchor_sim, values, loop=_env_bool("SIM_CLOCK_LOOP", True))
    if mode == "latest" and values:
        anchor_sim = values[-1]
    return {
        "anchor_real": _format_real(real_now),
        "anchor_sim": anchor_sim.strftime(TIME_FMT),
        "speed": _default_speed(mode),
        "loop": _env_bool("SIM_CLOCK_LOOP", True),
        "paused": mode in {"fixed", "latest"},
        "mode": mode,
        "interval_seconds": _env_float("SIM_CLOCK_INTERVAL", 1.0),
        "poll_seconds": _env_float("SIM_CLOCK_POLL", 1.0),
    }


def _normalize_item(item: Mapping[str, Any] | None) -> dict[str, Any]:
    default = _initial_state()
    if not item:
        return default
    mode = str(item.get("mode") or default["mode"]).strip().casefold()
    if mode not in MODES:
        mode = _DEFAULT_MODE
    try:
        anchor_sim = parse_time(item.get("anchor_sim"))
    except ValueError:
        anchor_sim = parse_time(default["anchor_sim"])
    try:
        speed = float(item.get("speed", default["speed"]))
    except (TypeError, ValueError):
        speed = float(default["speed"])
    if speed <= 0:
        speed = float(default["speed"])
    try:
        interval = float(item.get("interval_seconds", default["interval_seconds"]))
    except (TypeError, ValueError):
        interval = float(default["interval_seconds"])
    try:
        poll = float(item.get("poll_seconds", default["poll_seconds"]))
    except (TypeError, ValueError):
        poll = float(default["poll_seconds"])
    return {
        "anchor_real": _format_real(_parse_real(item.get("anchor_real"))),
        "anchor_sim": anchor_sim.strftime(TIME_FMT),
        "speed": speed,
        "loop": bool(item.get("loop", default["loop"])),
        "paused": bool(item.get("paused", default["paused"])),
        "mode": mode,
        "interval_seconds": interval if interval > 0 else 1.0,
        "poll_seconds": poll if poll > 0 else 1.0,
    }


def _load_state() -> dict[str, Any]:
    repository = get_repository()
    stored = repository.get_clock()
    if stored is None:
        return _normalize_item(repository.put_clock(_initial_state()))
    return _normalize_item(stored)


def _save_state(value: Mapping[str, Any]) -> dict[str, Any]:
    return _normalize_item(get_repository().put_clock(_normalize_item(value)))


def _bound(value: datetime, values: list[datetime], *, loop: bool) -> datetime:
    value = value.replace(tzinfo=None, second=0, microsecond=0)
    if not values:
        return value
    start, end = values[0], values[-1]
    if start == end:
        return start
    if start <= value <= end:
        return value
    if not loop:
        return min(max(value, start), end)
    span = (end - start).total_seconds()
    offset = (value - start).total_seconds() % span
    return (start + timedelta(seconds=offset)).replace(second=0, microsecond=0)


def _current(item: Mapping[str, Any], now: datetime | None = None) -> datetime:
    anchor_sim = parse_time(item["anchor_sim"])
    if item.get("paused") or item.get("mode") == "latest":
        if item.get("mode") == "latest":
            values = _timeline_values()
            return values[-1] if values else anchor_sim
        return _bound(anchor_sim, _timeline_values(), loop=bool(item.get("loop")))
    real_now = now or _real_now()
    elapsed = max(0.0, (real_now - _parse_real(item["anchor_real"])).total_seconds())
    target = anchor_sim + timedelta(seconds=elapsed * float(item["speed"]))
    return _bound(target, _timeline_values(), loop=bool(item.get("loop")))


def _timeline_index(values: list[datetime], current: datetime) -> int | None:
    if not values:
        return None
    index = 0
    for position, value in enumerate(values):
        if value > current:
            break
        index = position
    return index


def _next_change(item: Mapping[str, Any], now: datetime | None = None) -> float | None:
    if item.get("paused") or item.get("mode") not in _PLAYING_MODES:
        return None
    speed = float(item["speed"])
    real_now = now or _real_now()
    elapsed_sim = max(
        0.0,
        (real_now - _parse_real(item["anchor_real"])).total_seconds() * speed,
    )
    remaining_sim = 60.0 - (elapsed_sim % 60.0)
    return round(remaining_sim / speed, 2)


def state() -> dict[str, Any]:
    """Return a state projection calculated from the persisted anchors."""

    item = _load_state()
    now = _real_now()
    current = _current(item, now)
    values = _timeline_values()
    next_change = _next_change(item, now)
    configured_mode = str(item["mode"])
    paused = bool(item["paused"])
    return {
        "mode": "fixed" if paused else configured_mode,
        "configured_mode": configured_mode,
        "is_overridden": False,
        "is_paused": paused,
        "is_playing": configured_mode in _PLAYING_MODES and not paused,
        "is_continuous": configured_mode == "live" and not paused,
        "paused": paused,
        "anchor_real": item["anchor_real"],
        "anchor_sim": item["anchor_sim"],
        "sim_time": current.strftime(TIME_FMT),
        "sim_time_iso": current.isoformat(),
        "real_time": now.astimezone().strftime(TIME_FMT),
        "speed": float(item["speed"]),
        "live_speed": float(item["speed"]),
        "interval_seconds": float(item["interval_seconds"]),
        "poll_seconds": float(item["poll_seconds"]),
        "loop": bool(item["loop"]),
        "next_change_in_seconds": next_change,
        "suggested_poll_seconds": next_change or float(item["poll_seconds"]),
        "timeline_start": values[0].strftime(TIME_FMT) if values else None,
        "timeline_end": values[-1].strftime(TIME_FMT) if values else None,
        "timeline_size": len(values),
        "timeline_index": _timeline_index(values, current),
        "active_freeze_count": 0,
        "active_run_ids": [],
    }


def live_state() -> dict[str, Any]:
    """Return the stream-player contract using the same authoritative clock."""

    current_state = state()
    values = _timeline_values()
    current = parse_time(current_state["sim_time"])
    span_seconds = (
        max((values[-1] - values[0]).total_seconds(), 60.0)
        if len(values) > 1
        else 60.0
    )
    progress = (
        max(0.0, (current - values[0]).total_seconds()) if values else 0.0
    )
    return {
        "timeline": [value.strftime(TIME_FMT) for value in values],
        "timeline_size": len(values),
        "timeline_start": values[0].strftime(TIME_FMT) if values else None,
        "timeline_end": values[-1].strftime(TIME_FMT) if values else None,
        "span_minutes": round(span_seconds / 60.0),
        "live_time": current.strftime(TIME_FMT),
        "live_progress_minutes": int(progress // 60),
        "slice_index": _timeline_index(values, current),
        "cycle": 0,
        "loop": bool(current_state["loop"]),
        "speed": float(current_state["speed"]),
        "is_real_time": abs(float(current_state["speed"]) - 1.0) < 1e-9,
        "next_minute_in_seconds": current_state["next_change_in_seconds"],
        "server_time": current_state["real_time"],
        "paused": current_state["is_paused"],
    }


def now_str() -> str:
    return str(state()["sim_time"])


def resolve(explicit: object = None) -> str:
    if explicit is None or (isinstance(explicit, str) and not explicit.strip()):
        return now_str()
    return parse_time(explicit).strftime(TIME_FMT)


def configure(
    *,
    mode: str | None = None,
    sim_time: object = None,
    speed: float | None = None,
    interval: float | None = None,
    loop: bool | None = None,
    poll: float | None = None,
    paused: bool | None = None,
) -> dict[str, Any]:
    item = _load_state()
    now = _real_now()
    current = _current(item, now)
    if mode is not None:
        normalized_mode = str(mode).strip().casefold()
        if normalized_mode not in MODES:
            raise ValueError(f"mode 必須是 {', '.join(MODES)} 之一")
        item["mode"] = normalized_mode
    if speed is not None:
        try:
            normalized_speed = float(speed)
        except (TypeError, ValueError) as exc:
            raise ValueError("speed 必須是數字") from exc
        if normalized_speed <= 0:
            raise ValueError("speed 必須大於 0")
        item["speed"] = normalized_speed
    if interval is not None:
        try:
            normalized_interval = float(interval)
        except (TypeError, ValueError) as exc:
            raise ValueError("interval 必須是數字") from exc
        if normalized_interval <= 0:
            raise ValueError("interval 必須大於 0")
        item["interval_seconds"] = normalized_interval
    if poll is not None:
        try:
            normalized_poll = float(poll)
        except (TypeError, ValueError) as exc:
            raise ValueError("poll 必須是數字") from exc
        if normalized_poll <= 0:
            raise ValueError("poll 必須大於 0")
        item["poll_seconds"] = normalized_poll
    if loop is not None:
        if not isinstance(loop, bool):
            raise ValueError("loop 必須是布林值")
        item["loop"] = loop
    if sim_time is not None:
        current = parse_time(sim_time)
    values = _timeline_values()
    current = _bound(current, values, loop=bool(item["loop"]))
    if item["mode"] == "latest" and values:
        current = values[-1]
    if paused is not None:
        if not isinstance(paused, bool):
            raise ValueError("paused 必須是布林值")
        item["paused"] = paused
    elif mode is not None:
        item["paused"] = item["mode"] in {"fixed", "latest"}
    item["anchor_real"] = _format_real(now)
    item["anchor_sim"] = current.strftime(TIME_FMT)
    _save_state(item)
    return state()


def advance(*, minutes: float | None = None, steps: int | None = None) -> dict[str, Any]:
    if (minutes is None) == (steps is None):
        raise ValueError("minutes 與 steps 必須且只能提供一項")
    item = _load_state()
    now = _real_now()
    current = _current(item, now)
    values = _timeline_values()
    if steps is not None:
        if isinstance(steps, bool):
            raise ValueError("steps 必須是整數")
        try:
            offset = int(steps)
        except (TypeError, ValueError) as exc:
            raise ValueError("steps 必須是整數") from exc
        if float(steps) != offset:
            raise ValueError("steps 必須是整數")
        if values:
            index = _timeline_index(values, current) or 0
            target_index = index + offset
            if item["loop"]:
                target_index %= len(values)
            else:
                target_index = min(max(target_index, 0), len(values) - 1)
            current = values[target_index]
    else:
        if isinstance(minutes, bool):
            raise ValueError("minutes 必須是數字")
        try:
            current += timedelta(minutes=float(minutes))
        except (TypeError, ValueError) as exc:
            raise ValueError("minutes 必須是數字") from exc
        current = _bound(current, values, loop=bool(item["loop"]))
    item["anchor_real"] = _format_real(now)
    item["anchor_sim"] = current.strftime(TIME_FMT)
    _save_state(item)
    return state()


def pause() -> dict[str, Any]:
    item = _load_state()
    if not item["paused"]:
        now = _real_now()
        item["anchor_sim"] = _current(item, now).strftime(TIME_FMT)
        item["anchor_real"] = _format_real(now)
        item["paused"] = True
        _save_state(item)
    return state()


def resume() -> dict[str, Any]:
    item = _load_state()
    if item["paused"]:
        now = _real_now()
        item["anchor_real"] = _format_real(now)
        if item["mode"] in {"fixed", "latest"}:
            item["mode"] = _DEFAULT_MODE
        item["paused"] = False
        _save_state(item)
    return state()


def reset() -> dict[str, Any]:
    _save_state(_initial_state())
    return state()


__all__ = [
    "MODES",
    "TIME_FMT",
    "advance",
    "configure",
    "live_state",
    "now_str",
    "parse_time",
    "pause",
    "reset",
    "resolve",
    "resume",
    "state",
    "timeline",
]
