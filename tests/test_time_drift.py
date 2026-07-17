"""TimeDriftSensor tests: wrap-around, anti-flicker, 10s rounding.

native_value is a pure read of coordinator.data['systemTime'] vs dt_util.utcnow,
so tests patch sensor.dt_util.utcnow to a fixed NOW and read native_value
directly — no HA state plumbing needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import custom_components.eveus.sensor as sensor_mod
from custom_components.eveus.sensor import TimeDriftSensor, _TIME_DRIFT_DESCRIPTION

_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


class _Coord:
    def __init__(self):
        self.data: dict = {}
        self.last_update_success = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


class _Charger:
    ip = "1.2.3.4"
    model_name = "Test"
    capabilities: set = set()


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch):
    monkeypatch.setattr(sensor_mod.dt_util, "utcnow", lambda: _NOW)


def _drift_for(offset_seconds):
    sensor = TimeDriftSensor(_Coord(), _Charger(), _TIME_DRIFT_DESCRIPTION, "smoke", "e1")
    sensor.coordinator.data = {"systemTime": _NOW + timedelta(seconds=offset_seconds)}
    return sensor.native_value


def test_clock_behind_is_negative():
    assert _drift_for(-3600) == -3600


def test_clock_ahead_is_positive():
    assert _drift_for(+3600) == 3600


def test_wrap_ahead_past_half_day_reads_as_behind():
    # 23h "ahead" -> raw drift 82800 > 43200 -> -86400 -> -3600
    assert _drift_for(+82800) == -3600


def test_wrap_behind_past_half_day_reads_as_ahead():
    # 23h "behind" -> raw drift -82800 < -43200 -> +86400 -> +3600
    assert _drift_for(-82800) == 3600


@pytest.mark.parametrize("offset", [0, 20, -20, 29, -29])
def test_anti_flicker_small_drift_is_zero(offset):
    assert _drift_for(offset) == 0


@pytest.mark.parametrize("offset,expected", [(47, 50), (43, 40), (-47, -50), (35, 40)])
def test_rounded_to_ten_seconds(offset, expected):
    assert _drift_for(offset) == expected


def test_missing_system_time_returns_none():
    sensor = TimeDriftSensor(_Coord(), _Charger(), _TIME_DRIFT_DESCRIPTION, "smoke", "e1")
    sensor.coordinator.data = {}
    assert sensor.native_value is None
