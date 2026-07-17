"""Daily sensor tests: midnight rollover, restore, negative-delta, cross-midnight.

The fragile logic lives in DailyEnergySensor / DailySessionTimeSensor
_handle_coordinator_update + async_added_to_hass (sensor.py). Each sensor is
built over a tiny stub coordinator; async_write_ha_state is stubbed to a no-op
so the accumulation logic can be driven directly, and the local date is
controlled by patching sensor.dt_util.now.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import State
from homeassistant.util import dt as dt_util

import custom_components.eveus.sensor as sensor_mod
from custom_components.eveus.sensor import DailyEnergySensor, DailySessionTimeSensor

_DAY = datetime(2026, 7, 1, 12, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
_NEXT_DAY = _DAY + timedelta(days=1)


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


@pytest.fixture
def clock(monkeypatch):
    """Control sensor.dt_util.now (and, transitively, start_of_local_day)."""
    holder = {"now": _DAY}
    monkeypatch.setattr(sensor_mod.dt_util, "now", lambda: holder["now"])
    return holder


def _make(cls):
    coord = _Coord()
    entity = cls(coord, _Charger(), "smoke", "e1")
    entity.async_write_ha_state = lambda: None  # bypass HA state plumbing
    return entity, coord


def _update(entity, coord, **data):
    coord.data = data
    entity._handle_coordinator_update()


# --------------------------------------------------------------------------- #
# DailyEnergySensor
# --------------------------------------------------------------------------- #

def test_daily_energy_accumulates_within_day(clock):
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)   # baseline set this day
    assert sensor.native_value == 0.0
    _update(sensor, coord, totalEnergy=105.5)
    assert sensor.native_value == 5.5


def test_daily_energy_midnight_rollover(clock):
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)
    _update(sensor, coord, totalEnergy=105.0)
    assert sensor.native_value == 5.0

    clock["now"] = _NEXT_DAY
    _update(sensor, coord, totalEnergy=110.0)   # new day -> baseline re-taken
    assert sensor.native_value == 0.0
    assert sensor._current_date == _NEXT_DAY.date()
    assert sensor._attr_last_reset is not None


async def test_daily_energy_restore_same_day(hass, clock, monkeypatch):
    sensor, coord = _make(DailyEnergySensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_daily_energy"
    today = _DAY.date().isoformat()
    monkeypatch.setattr(
        sensor, "async_get_last_state",
        AsyncMock(return_value=State(sensor.entity_id, "5.0",
                                     {"date": today, "baseline_kwh": 100.0})),
    )
    await sensor.async_added_to_hass()
    assert sensor._computed == 5.0
    assert sensor._baseline == 100.0

    # resumes accumulation from the restored baseline
    _update(sensor, coord, totalEnergy=108.0)
    assert sensor.native_value == 8.0


async def test_daily_energy_restore_stale_day_ignored(hass, clock, monkeypatch):
    sensor, coord = _make(DailyEnergySensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_daily_energy"
    yesterday = (_DAY - timedelta(days=1)).date().isoformat()
    monkeypatch.setattr(
        sensor, "async_get_last_state",
        AsyncMock(return_value=State(sensor.entity_id, "5.0",
                                     {"date": yesterday, "baseline_kwh": 100.0})),
    )
    await sensor.async_added_to_hass()
    assert sensor._computed is None      # not restored — different day
    assert sensor._baseline is None


# --------------------------------------------------------------------------- #
# DailySessionTimeSensor
# --------------------------------------------------------------------------- #

def test_daily_session_time_accumulates(clock):
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100)   # baseline this day
    _update(sensor, coord, sessionTime=3700)  # +3600s = 1h
    assert sensor.native_value == 1.0
    _update(sensor, coord, sessionTime=3700)  # no change
    assert sensor.native_value == 1.0


def test_daily_session_time_new_session_negative_delta(clock):
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100)
    _update(sensor, coord, sessionTime=3700)   # +3600 -> 1h
    _update(sensor, coord, sessionTime=30)     # new session (reset) -> negative delta ignored
    assert sensor._accumulated == 3600.0
    _update(sensor, coord, sessionTime=1830)   # +1800 from the new session
    assert sensor._accumulated == 5400.0
    assert sensor.native_value == 1.5


def test_daily_session_time_cross_midnight_split(clock):
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=0)      # session starts, baseline
    _update(sensor, coord, sessionTime=3600)   # +1h on day D
    assert sensor.native_value == 1.0

    clock["now"] = _NEXT_DAY
    _update(sensor, coord, sessionTime=7200)   # rollover: reset, prev re-anchored
    assert sensor.native_value == 0.0
    _update(sensor, coord, sessionTime=9000)   # +1800s = 0.5h on day D+1
    assert sensor.native_value == 0.5
    assert sensor._current_date == _NEXT_DAY.date()


async def test_daily_session_time_restore_same_day(hass, clock, monkeypatch):
    sensor, coord = _make(DailySessionTimeSensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_daily_session_time"
    today = _DAY.date().isoformat()
    monkeypatch.setattr(
        sensor, "async_get_last_state",
        AsyncMock(return_value=State(sensor.entity_id, "1.0",
                                     {"date": today, "accumulated_s": 3600.0, "prev_s": 3700.0})),
    )
    await sensor.async_added_to_hass()
    assert sensor._accumulated == 3600.0
    assert sensor._prev == 3700.0
    assert sensor.native_value == 1.0
