"""Unit tests for the authoritative common-timeline simulation clock."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend import sim_clock


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def elapse(self, seconds: float) -> None:
        self.value += seconds


def timestamps() -> list[pd.Timestamp]:
    return [
        pd.Timestamp("2026-05-20 17:00"),
        pd.Timestamp("2026-05-20 18:00"),
        pd.Timestamp("2026-05-20 19:00"),
        pd.Timestamp("2026-05-20 20:00"),
    ]


def make_clock(monkeypatch: pytest.MonkeyPatch) -> tuple[sim_clock.SimulationClock, FakeMonotonic]:
    monotonic = FakeMonotonic()
    monkeypatch.setenv("SIM_CLOCK_MODE", "playback")
    monkeypatch.setenv("SIM_CLOCK_INTERVAL", "1")
    monkeypatch.setenv("SIM_CLOCK_LOOP", "false")
    monkeypatch.delenv("SIM_CLOCK_START", raising=False)
    clock = sim_clock.SimulationClock(
        timeline_provider=timestamps,
        monotonic=monotonic,
    )
    return clock, monotonic


def test_common_timeline_uses_only_complete_source_intersection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    traffic = tmp_path / "traffic.csv"
    crowd = tmp_path / "crowd.csv"
    traffic.write_text(
        "Timestamp,Segment_ID,Road_Name,Avg_Speed,Vehicle_Count,Saturation_Score,Lane_Status\n"
        "2026-05-20 18:00,RD_1,Road 1,30,100,0.5,Normal\n"
        "2026-05-20 17:00,RD_1,Road 1,31,90,0.4,Normal\n"
        "2026-05-20 19:00,RD_1,Road 1,32,80,0.3,Normal\n"
        "2026-05-20 19:00,RD_1,Road 1,33,70,0.2,Normal\n",
        encoding="utf-8",
    )
    crowd.write_text(
        "Timestamp,BS_ID,Location_Name,User_Count,Stay_Time_Avg,Growth_Rate,Roaming_User_Pct\n"
        "2026-05-20 17:00,BS_1,Station 1,100,10,0.1,5%\n"
        "2026-05-20 18:00,BS_1,Station 1,200,20,0.2,6%\n"
        "2026-05-20 20:00,BS_1,Station 1,300,30,0.3,7%\n",
        encoding="utf-8",
    )
    # The clock resolves sources through data_source, so the fake sources are
    # injected at that boundary rather than as module-level paths.
    resolved = {
        sim_clock.TRAFFIC_FLOW_FILENAME: traffic,
        sim_clock.CROWD_DENSITY_FILENAME: crowd,
    }
    monkeypatch.setattr(sim_clock, "get_data_path", lambda filename: resolved[filename])
    sim_clock._timeline_cache.clear()

    assert sim_clock.timeline() == [
        pd.Timestamp("2026-05-20 17:00"),
        pd.Timestamp("2026-05-20 18:00"),
    ]


def test_play_pause_tick_reset_and_authoritative_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock, monotonic = make_clock(monkeypatch)

    assert clock.now() == timestamps()[0]
    monotonic.elapse(1)
    assert clock.now() == timestamps()[1]

    clock.pause()
    monotonic.elapse(20)
    assert clock.now() == timestamps()[1]

    clock.play()
    clock.tick()
    assert clock.now() == timestamps()[2]
    clock.advance(minutes=90)
    assert clock.now() == timestamps()[3]

    clock.reset()
    assert clock.now() == timestamps()[0]
    assert clock.state()["timeline_index"] == 0


def test_freeze_leases_are_per_run_idempotent_and_restore_playback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock, monotonic = make_clock(monkeypatch)
    monotonic.elapse(1)
    frozen_at = clock.now()

    first = clock.acquire_freeze("run-1")
    assert clock.acquire_freeze("run-1") is first
    second = clock.acquire_freeze("run-2")
    assert clock.state()["active_freeze_count"] == 2

    monotonic.elapse(20)
    assert clock.now() == frozen_at
    with pytest.raises(sim_clock.ClockFrozenError):
        clock.tick()
    with pytest.raises(sim_clock.ClockFrozenError):
        clock.play()
    with pytest.raises(sim_clock.ClockFrozenError):
        clock.advance(steps=1)
    with pytest.raises(sim_clock.ClockFrozenError):
        clock.reset()

    clock.release_freeze(first)
    assert clock.now() == frozen_at
    assert clock.state()["is_playing"] is False

    clock.release_freeze(second)
    assert clock.now() == frozen_at
    assert clock.state()["is_playing"] is True
    clock.release_freeze(second)
    assert clock.state()["active_freeze_count"] == 0

    monotonic.elapse(1)
    assert clock.now() == timestamps()[2]


def test_last_freeze_release_restores_preexisting_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock, monotonic = make_clock(monkeypatch)
    clock.pause()
    lease = clock.acquire_freeze("run-paused")

    monotonic.elapse(10)
    clock.release_freeze(lease)

    assert clock.now() == timestamps()[0]
    assert clock.state()["is_paused"] is True
