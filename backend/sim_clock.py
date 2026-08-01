"""Authoritative, discrete simulation clock shared by monitoring and incident response.

The clock only exposes timestamps that are complete in both traffic and crowd sources.
It supports an explicit command model and idempotent per-run freeze leases so incident
processing cannot race dashboard time advancement.
"""

from __future__ import annotations

import bisect
import logging
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - the clock works without dotenv
    pass

logger = logging.getLogger(__name__)

from backend.data_source import get_data_path

TRAFFIC_FLOW_FILENAME = "city_traffic_flow.csv"
CROWD_DENSITY_FILENAME = "signaling_crowd_density.csv"

TIME_FMT = "%Y-%m-%d %H:%M"
MODES = ("playback", "fixed", "latest", "smooth", "auto")
PLAYING_MODES = frozenset({"playback", "smooth", "auto"})
CONTINUOUS_MODES: tuple[str, ...] = ()

DEFAULT_MODE = "playback"
DEFAULT_INTERVAL = 1.0
DEFAULT_SPEED = 60.0
DEFAULT_POLL = 1.0
DEFAULT_LOOP = False

_TRAFFIC_REQUIRED_COLUMNS = (
    "Timestamp",
    "Segment_ID",
    "Road_Name",
    "Avg_Speed",
    "Vehicle_Count",
    "Saturation_Score",
    "Lane_Status",
)
_TRAFFIC_NUMERIC_COLUMNS = ("Avg_Speed", "Vehicle_Count", "Saturation_Score")
_CROWD_REQUIRED_COLUMNS = (
    "Timestamp",
    "BS_ID",
    "Location_Name",
    "User_Count",
    "Stay_Time_Avg",
    "Growth_Rate",
    "Roaming_User_Pct",
)
_CROWD_NUMERIC_COLUMNS = ("User_Count", "Stay_Time_Avg", "Growth_Rate")

_timeline_cache: dict[str, object] = {}
_timeline_lock = threading.Lock()


def _data_paths() -> tuple[Path, Path]:
    """Resolve the clock's two sources, preferring S3 and falling back to data/."""

    return (
        get_data_path(TRAFFIC_FLOW_FILENAME),
        get_data_path(CROWD_DENSITY_FILENAME),
    )


def _non_empty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def complete_slice_timestamps(
    path: Path,
    *,
    id_column: str,
    required_columns: Iterable[str],
    numeric_columns: Iterable[str] = (),
) -> set[pd.Timestamp]:
    """Return timestamps whose entire source slice satisfies the clock contract.

    This is intentionally limited to the validation needed to construct the clock.
    The snapshot service performs the richer source validation and evidence capture.
    """

    if not path.exists():
        return set()
    required = tuple(required_columns)
    try:
        frame = pd.read_csv(path, dtype=object)
    except Exception as exc:
        logger.warning("時間軸載入失敗 (%s): %s: %s", path.name, type(exc).__name__, exc)
        return set()

    if frame.empty or any(column not in frame.columns for column in required):
        return set()

    parsed_times = pd.to_datetime(frame["Timestamp"], format=TIME_FMT, errors="coerce")
    valid_times: set[pd.Timestamp] = set()
    for timestamp, positions in frame.loc[parsed_times.notna()].groupby(parsed_times[parsed_times.notna()]).groups.items():
        source_slice = frame.loc[positions]
        if source_slice.empty:
            continue
        if any(not _non_empty(source_slice[column]).all() for column in required):
            continue
        identifiers = source_slice[id_column].astype(str).str.strip()
        if identifiers.duplicated().any():
            continue
        if any(
            pd.to_numeric(source_slice[column], errors="coerce").isna().any()
            for column in numeric_columns
        ):
            continue
        valid_times.add(pd.Timestamp(timestamp))
    return valid_times


def build_common_timeline(
    traffic_times: Iterable[object], crowd_times: Iterable[object]
) -> list[pd.Timestamp]:
    """Build the ascending intersection of already-complete source timestamps."""

    def normalize(values: Iterable[object]) -> set[pd.Timestamp]:
        normalized: set[pd.Timestamp] = set()
        for value in values:
            parsed = parse_time(value)
            if parsed is not None:
                normalized.add(parsed)
        return normalized

    return sorted(normalize(traffic_times) & normalize(crowd_times))


def _cache_key(paths: tuple[Path, Path]) -> tuple:
    return tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in paths)


def timeline() -> list[pd.Timestamp]:
    """Return the ascending common timeline of complete Traffic and Crowd slices.

    Sources resolve through ``data_source.get_data_path``, so the timeline follows
    the S3 copy when a bucket is configured and the packaged ``data/`` copy otherwise.
    """

    traffic_path, crowd_path = _data_paths()
    key = _cache_key((traffic_path, crowd_path))
    with _timeline_lock:
        if _timeline_cache.get("key") != key:
            traffic_times = complete_slice_timestamps(
                traffic_path,
                id_column="Segment_ID",
                required_columns=_TRAFFIC_REQUIRED_COLUMNS,
                numeric_columns=_TRAFFIC_NUMERIC_COLUMNS,
            )
            crowd_times = complete_slice_timestamps(
                crowd_path,
                id_column="BS_ID",
                required_columns=_CROWD_REQUIRED_COLUMNS,
                numeric_columns=_CROWD_NUMERIC_COLUMNS,
            )
            _timeline_cache["key"] = key
            _timeline_cache["timeline"] = tuple(
                build_common_timeline(traffic_times, crowd_times)
            )
        return list(_timeline_cache.get("timeline", ()))


def parse_time(value: object) -> pd.Timestamp | None:
    """Parse a timestamp, returning ``None`` for empty or invalid values."""

    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value
    if isinstance(value, datetime):
        return pd.Timestamp(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = pd.Timestamp(text)
        return None if pd.isna(parsed) else parsed
    except Exception:
        logger.warning("無法解析時間: %r", value)
        return None


def _index_at_or_before(values: list[pd.Timestamp], timestamp: pd.Timestamp) -> int:
    return max(0, bisect.bisect_right(values, timestamp) - 1)


def snap(timestamp: pd.Timestamp) -> pd.Timestamp:
    """Snap arbitrary time to the latest authoritative common slice at or before it."""

    values = timeline()
    if not values:
        return timestamp
    return values[_index_at_or_before(values, timestamp)]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s 不是數字 (%r)，改用預設 %s", name, raw, default)
        return default
    return value if value > 0 else default


_override: ContextVar[pd.Timestamp | None] = ContextVar("sim_time_override", default=None)


@contextmanager
def override(value: object = None):
    """Temporarily resolve the current request at an explicit time."""

    timestamp = parse_time(value)
    if timestamp is None:
        yield None
        return
    token = _override.set(timestamp)
    try:
        yield timestamp
    finally:
        _override.reset(token)


@dataclass(frozen=True, slots=True)
class FreezeLease:
    """An idempotent lease associated with exactly one incident run."""

    run_id: str


class ClockFrozenError(ValueError):
    """Raised when a command would change a clock held by active runs."""


class SimulationClock:
    """Thread-safe authoritative clock over a discrete common timeline."""

    def __init__(
        self,
        timeline_provider: Callable[[], Iterable[pd.Timestamp]] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._timeline_provider = timeline_provider or timeline
        self._monotonic = monotonic or time.monotonic
        self._freeze_leases: dict[str, FreezeLease] = {}
        self._pre_freeze_mode: str | None = None
        self._pre_freeze_time: pd.Timestamp | None = None
        self._prev_mode: str | None = None
        self.reset()

    def common_timeline(self) -> list[pd.Timestamp]:
        return sorted(set(pd.Timestamp(value) for value in self._timeline_provider()))

    def reset(self) -> dict:
        """Reset to the first common slice and environment-defined playback mode."""

        with self._lock:
            self._require_unfrozen("reset")
            configured_mode = (os.environ.get("SIM_CLOCK_MODE") or DEFAULT_MODE).strip().lower()
            if configured_mode not in MODES:
                logger.warning(
                    "SIM_CLOCK_MODE=%r 不支援，改用 %s", configured_mode, DEFAULT_MODE
                )
                configured_mode = DEFAULT_MODE
            self.mode = configured_mode
            self.interval = _env_float("SIM_CLOCK_INTERVAL", DEFAULT_INTERVAL)
            self.speed = _env_float("SIM_CLOCK_SPEED", DEFAULT_SPEED)
            self.poll = _env_float("SIM_CLOCK_POLL", DEFAULT_POLL)
            self.loop = _env_bool("SIM_CLOCK_LOOP", DEFAULT_LOOP)
            self._prev_mode = None
            values = self.common_timeline()
            start = parse_time(os.environ.get("SIM_CLOCK_START"))
            self._anchor(start if start is not None else self._timeline_start(values))
            return self.state()

    def configure(
        self,
        mode: str | None = None,
        sim_time: object = None,
        speed: float | None = None,
        interval: float | None = None,
        loop: bool | None = None,
        poll: float | None = None,
    ) -> dict:
        with self._lock:
            self._require_unfrozen("configure")
            current = self.now()
            normalized_mode = self.mode
            if mode is not None:
                normalized_mode = str(mode).strip().lower()
                if normalized_mode not in MODES:
                    raise ValueError(f"mode 必須是 {', '.join(MODES)} 之一，收到 {mode!r}")
            target = parse_time(sim_time)
            if sim_time is not None and target is None:
                raise ValueError(f"無法解析 sim_time: {sim_time!r}")
            if speed is not None and float(speed) <= 0:
                raise ValueError("speed 必須大於 0")
            if interval is not None and float(interval) <= 0:
                raise ValueError("interval 必須大於 0")
            if poll is not None and float(poll) <= 0:
                raise ValueError("poll 必須大於 0")

            self.mode = normalized_mode
            self.speed = float(speed) if speed is not None else self.speed
            self.interval = float(interval) if interval is not None else self.interval
            self.poll = float(poll) if poll is not None else self.poll
            self.loop = bool(loop) if loop is not None else self.loop
            self._prev_mode = None
            self._anchor(target if target is not None else current)
            return self.state()

    def play(self) -> dict:
        """Start discrete playback from the authoritative current slice."""

        with self._lock:
            self._require_unfrozen("play")
            current = self.now()
            if self.mode not in PLAYING_MODES:
                resume_mode = self._prev_mode if self._prev_mode in PLAYING_MODES else DEFAULT_MODE
                self.mode = resume_mode
                self._prev_mode = None
            self._anchor(current)
            return self.state()

    def resume(self) -> dict:
        return self.play()

    def pause(self) -> dict:
        """Pause without altering the mode saved by an active freeze lease."""

        with self._lock:
            if self._freeze_leases:
                return self.state()
            current = self.now()
            if self.mode != "fixed":
                self._prev_mode = self.mode
            self._anchor(current)
            self.mode = "fixed"
            return self.state()

    def tick(self) -> dict:
        """Advance one common slice when playing; paused ticks are no-ops."""

        with self._lock:
            self._require_unfrozen("tick")
            if self.mode not in PLAYING_MODES:
                return self.state()
            self._move_steps(1)
            return self.state()

    def advance(self, minutes: float | None = None, steps: int | None = None) -> dict:
        """Manually move along the common timeline without leaving it."""

        with self._lock:
            self._require_unfrozen("advance")
            if minutes is not None and steps is not None:
                raise ValueError("minutes 與 steps 只能提供一項")
            if steps is not None:
                self._move_steps(int(steps))
            elif minutes is not None:
                target = self.now() + timedelta(minutes=float(minutes))
                self._anchor(target)
            else:
                raise ValueError("請提供 minutes 或 steps")
            return self.state()

    def acquire_freeze(self, run_id: str) -> FreezeLease:
        """Acquire an idempotent freeze lease for an incident run."""

        normalized_run_id = str(run_id).strip()
        if not normalized_run_id:
            raise ValueError("run_id 不可為空")
        with self._lock:
            existing = self._freeze_leases.get(normalized_run_id)
            if existing is not None:
                return existing
            if not self._freeze_leases:
                frozen_time = self.now()
                self._pre_freeze_mode = self.mode
                self._pre_freeze_time = frozen_time
                self._anchor(frozen_time)
                self.mode = "fixed"
            lease = FreezeLease(run_id=normalized_run_id)
            self._freeze_leases[normalized_run_id] = lease
            return lease

    def release_freeze(self, lease: FreezeLease | str) -> dict:
        """Release once per run; duplicate or unknown releases are harmless."""

        run_id = lease.run_id if isinstance(lease, FreezeLease) else str(lease).strip()
        with self._lock:
            if run_id not in self._freeze_leases:
                return self.state()
            del self._freeze_leases[run_id]
            if not self._freeze_leases:
                restore_time = self._pre_freeze_time or self._anchor_sim
                restore_mode = self._pre_freeze_mode or "fixed"
                self.mode = restore_mode
                self._anchor(restore_time)
                self._pre_freeze_mode = None
                self._pre_freeze_time = None
            return self.state()

    def now(self) -> pd.Timestamp:
        """Return the authoritative current common-slice timestamp."""

        forced = _override.get()
        if forced is not None:
            return forced
        with self._lock:
            values = self.common_timeline()
            if not values:
                return self._anchor_sim
            if self.mode == "latest":
                return values[-1]
            if self.mode == "fixed":
                return self._snap_to_timeline(self._anchor_sim, values)
            elapsed = max(0.0, self._monotonic() - self._anchor_real)
            steps = int(elapsed // self.interval)
            start_index = _index_at_or_before(values, self._anchor_sim)
            return values[self._bounded_index(start_index + steps, len(values))]

    def resolve(self, explicit: object = None) -> pd.Timestamp:
        timestamp = parse_time(explicit)
        return timestamp if timestamp is not None else self.now()

    def timeline_start(self) -> pd.Timestamp:
        return self._timeline_start(self.common_timeline())

    def timeline_end(self) -> pd.Timestamp:
        values = self.common_timeline()
        return values[-1] if values else pd.Timestamp.now().floor("min")

    def next_change_in_seconds(self) -> float | None:
        if _override.get() is not None:
            return None
        with self._lock:
            if self.mode not in PLAYING_MODES or self._freeze_leases:
                return None
            values = self.common_timeline()
            current = self.now()
            if not values or (not self.loop and current == values[-1]):
                return None
            elapsed = max(0.0, self._monotonic() - self._anchor_real)
            return round(self.interval - (elapsed % self.interval), 2)

    def suggested_poll_seconds(self) -> float | None:
        return self.next_change_in_seconds()

    def state(self) -> dict:
        values = self.common_timeline()
        current = self.now()
        forced = _override.get()
        with self._lock:
            return {
                "mode": "override" if forced is not None else self.mode,
                "configured_mode": self.mode,
                "is_overridden": forced is not None,
                "is_paused": self.mode == "fixed",
                "is_playing": self.mode in PLAYING_MODES and not self._freeze_leases,
                "is_continuous": False,
                "sim_time": current.strftime(TIME_FMT),
                "sim_time_iso": current.isoformat(),
                "real_time": datetime.now().strftime(TIME_FMT),
                "speed": self.speed,
                "interval_seconds": self.interval,
                "loop": self.loop,
                "next_change_in_seconds": self.next_change_in_seconds(),
                "suggested_poll_seconds": self.suggested_poll_seconds(),
                "timeline_start": values[0].strftime(TIME_FMT) if values else None,
                "timeline_end": values[-1].strftime(TIME_FMT) if values else None,
                "timeline_size": len(values),
                "timeline_index": _index_at_or_before(values, current) if values else None,
                "active_freeze_count": len(self._freeze_leases),
                "active_run_ids": tuple(sorted(self._freeze_leases)),
            }

    def _require_unfrozen(self, command: str) -> None:
        if self._freeze_leases:
            raise ClockFrozenError(
                f"Simulation Clock 已由 {len(self._freeze_leases)} 個執行中 Incident Run 凍結，拒絕 {command}"
            )

    def _move_steps(self, steps: int) -> None:
        values = self.common_timeline()
        if not values:
            return
        current_index = _index_at_or_before(values, self.now())
        self._anchor(values[self._bounded_index(current_index + steps, len(values))])

    def _anchor(self, simulation_time: pd.Timestamp) -> None:
        values = self.common_timeline()
        self._anchor_sim = self._snap_to_timeline(pd.Timestamp(simulation_time), values)
        self._anchor_real = self._monotonic()

    def _snap_to_timeline(
        self, timestamp: pd.Timestamp, values: list[pd.Timestamp]
    ) -> pd.Timestamp:
        if not values:
            return timestamp
        return values[_index_at_or_before(values, timestamp)]

    def _bounded_index(self, index: int, size: int) -> int:
        if size <= 0:
            return 0
        if self.loop:
            return index % size
        return min(max(index, 0), size - 1)

    @staticmethod
    def _timeline_start(values: list[pd.Timestamp]) -> pd.Timestamp:
        return values[0] if values else pd.Timestamp.now().floor("min")


clock = SimulationClock()


def now() -> pd.Timestamp:
    return clock.now()


def resolve(explicit: object = None) -> pd.Timestamp:
    return clock.resolve(explicit)


def now_str() -> str:
    return clock.now().strftime(TIME_FMT)


def state() -> dict:
    return clock.state()
