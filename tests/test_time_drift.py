"""TimeDriftSensor tests: wrap-around, anti-flicker, 10s rounding.

native_value is a pure read of coordinator.data['systemTime'] vs dt_util.utcnow,
so tests patch sensor.dt_util.utcnow to a fixed NOW and read native_value
directly — no HA state plumbing needed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.eveus.charger.v1 import ChargerV1
from custom_components.eveus.charger.v2 import ChargerV2
import custom_components.eveus.sensor as sensor_mod
from custom_components.eveus.sensor import _TIME_DRIFT_DESCRIPTION, TimeDriftSensor

_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


class _Coord:
    def __init__(self):
        self.data: dict = {}
        self.last_update_success = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch):
    monkeypatch.setattr(sensor_mod.dt_util, "utcnow", lambda: _NOW)


def _drift_for(offset_seconds, charger=None):
    charger = charger if charger is not None else ChargerV1("1.2.3.4", None, None)
    sensor = TimeDriftSensor(_Coord(), charger, _TIME_DRIFT_DESCRIPTION, "smoke", "e1")
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


def test_v1_wrap_survives_a_clock_reading_before_midnight():
    # V1 sends HH:MM:SS glued to today's date: 12:39 tomorrow vs 12:00 today
    # reads as -45480s raw, which is really +40920s of drift.
    assert _drift_for(-45480) == 40920


def test_v2_does_not_wrap_a_real_drift():
    """V2 sends an absolute timestamp — wrapping would hide the worst case.

    A station 13h ahead used to read as 11h behind: a plausible-looking number
    that no alert would ever fire on.
    """
    assert _drift_for(+46800, charger=ChargerV2("1.2.3.4", None, None)) == 46800


@pytest.mark.parametrize("offset", [0, 20, -20, 29, -29])
def test_anti_flicker_small_drift_is_zero(offset):
    assert _drift_for(offset) == 0


@pytest.mark.parametrize("offset,expected", [(47, 50), (43, 40), (-47, -50), (35, 40)])
def test_rounded_to_ten_seconds(offset, expected):
    assert _drift_for(offset) == expected


@pytest.mark.parametrize("data", [{}, {"state": 2}])
def test_missing_system_time_returns_none(data):
    """Both the empty-payload guard and the missing-key branch.

    An empty dict is falsy, so it never reaches the .get() — covering only that
    case left `data["systemTime"]` instead of `.get()` free to pass.
    """
    sensor = TimeDriftSensor(
        _Coord(), ChargerV1("1.2.3.4", None, None), _TIME_DRIFT_DESCRIPTION, "smoke", "e1"
    )
    sensor.coordinator.data = data
    assert sensor.native_value is None
