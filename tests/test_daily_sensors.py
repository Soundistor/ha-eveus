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

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import State
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

import custom_components.eveus.sensor as sensor_mod
from custom_components.eveus.sensor import (
    DailyEnergySensor,
    DailySessionTimeSensor,
    LastSessionSensor,
)

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


def test_daily_energy_recovers_when_the_day_turned_over_without_a_total(clock):
    """A None at rollover used to kill the sensor until the next midnight.

    Only the rollover branch ever set a baseline, so once it was fixed as None
    no later poll of that day could bring it back.
    """
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord)                       # no totalEnergy key at all
    assert sensor.native_value is None
    assert sensor._baseline is None

    _update(sensor, coord, totalEnergy=100.0)    # picks the baseline up
    _update(sensor, coord, totalEnergy=105.5)
    assert sensor.native_value == 5.5


def test_daily_energy_survives_a_lifetime_counter_reset(clock):
    """IEM2 is byte-for-byte totalEnergy and the user can zero it (KB-03 BUG-7).

    Clamping the negative delta to 0 froze the sensor until midnight even while
    the car was charging.
    """
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)
    _update(sensor, coord, totalEnergy=105.0)
    assert sensor.native_value == 5.0
    last_reset = sensor._attr_last_reset

    _update(sensor, coord, totalEnergy=3.0)      # reset in the station's web UI
    assert sensor.native_value == 5.0, "the day accumulated so far must survive"
    _update(sensor, coord, totalEnergy=8.0)
    assert sensor.native_value == 10.0
    assert sensor._attr_last_reset == last_reset, "a counter reset is not a new day"


async def test_daily_energy_keeps_the_day_across_a_reset_and_restart(hass, clock):
    """The rebase must not need a field that is never persisted.

    Storing the pre-reset total in a new attribute would have had to reach
    extra_restore_state_data too — the accumulated value already lives in
    `computed`, so subtracting it is what makes a restart safe.
    """
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)
    _update(sensor, coord, totalEnergy=105.0)
    _update(sensor, coord, totalEnergy=3.0)      # reset
    _update(sensor, coord, totalEnergy=8.0)
    assert sensor.native_value == 10.0
    stored = sensor.extra_restore_state_data.as_dict()

    restarted, coord2 = _make(DailyEnergySensor)
    restarted.hass = hass
    restarted.entity_id = "sensor.eveus_daily_energy"
    mock_restore_cache_with_extra_data(
        hass, ((State(restarted.entity_id, STATE_UNAVAILABLE), stored),)
    )
    await restarted.async_added_to_hass()

    _update(restarted, coord2, totalEnergy=9.0)
    assert restarted.native_value == 11.0


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


# --------------------------------------------------------------------------- #
# Restore across an offline restart (the 2026-08-13 prod bug)
# --------------------------------------------------------------------------- #

async def test_daily_energy_survives_unavailable_shutdown(hass, clock):
    """The bug: HA writes no attributes for an unavailable entity.

    The charger is offline most of the time, so a restart while it is down used
    to leave nothing to restore from and Daily Energy started the day at zero.
    The values now travel in the entity's own payload, which availability does
    not touch.
    """
    sensor, coord = _make(DailyEnergySensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_daily_energy"
    today = _DAY.date().isoformat()
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(sensor.entity_id, STATE_UNAVAILABLE),  # no attributes at all
                {"date": today, "baseline_kwh": 100.0, "computed": 5.0},
            ),
        ),
    )

    await sensor.async_added_to_hass()

    assert sensor._baseline == 100.0
    assert sensor._computed == 5.0
    _update(sensor, coord, totalEnergy=108.0)
    assert sensor.native_value == 8.0, "the day must continue, not restart at zero"


async def test_daily_session_time_survives_unavailable_shutdown(hass, clock):
    sensor, coord = _make(DailySessionTimeSensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_daily_session_time"
    today = _DAY.date().isoformat()
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(sensor.entity_id, STATE_UNAVAILABLE),
                {"date": today, "accumulated_s": 3600.0, "prev_s": 3700.0},
            ),
        ),
    )

    await sensor.async_added_to_hass()

    assert sensor._accumulated == 3600.0
    assert sensor._prev == 3700.0


@pytest.mark.parametrize(
    "payload",
    [
        {"accumulated_s": "unknown", "prev_s": 3700.0},
        {"accumulated_s": 3600.0, "prev_s": "unknown"},
        {"accumulated_s": None, "prev_s": None},
    ],
)
async def test_daily_session_time_survives_a_corrupted_payload(hass, clock, payload):
    """A bad stored value must not keep the entity from being added.

    DailyEnergySensor already guards the same conversion; this one raised
    ValueError/TypeError straight out of async_added_to_hass.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_daily_session_time"
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(sensor.entity_id, STATE_UNAVAILABLE),
                {"date": _DAY.date().isoformat(), **payload},
            ),
        ),
    )

    await sensor.async_added_to_hass()

    assert sensor._accumulated == 0.0
    assert sensor.native_value == 0.0


def _last_session(field="energy_kwh"):
    coord = _Coord()
    coord.last_session = None
    description = (
        sensor_mod._LAST_SESSION_ENERGY_DESCRIPTION
        if field == "energy_kwh"
        else sensor_mod._LAST_SESSION_DURATION_DESCRIPTION
    )
    entity = LastSessionSensor(coord, _Charger(), description, "smoke", "e1", field)
    entity.async_write_ha_state = lambda: None
    return entity, coord


async def test_last_session_survives_unavailable_shutdown(hass, clock):
    """The snapshot of a finished session must outlive an offline restart.

    It was left on async_get_last_state(), which returns "unavailable" whenever
    HA shut down while the charger was offline — the normal case for this device
    since setup stopped waiting for a poll. coordinator.last_session is None
    after a restart too, so there was nothing to recover from.
    """
    sensor, _ = _last_session()
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_last_session_energy"
    mock_restore_cache_with_extra_data(
        hass,
        ((State(sensor.entity_id, STATE_UNAVAILABLE), {"computed": 12.5}),),
    )

    await sensor.async_added_to_hass()

    assert sensor.native_value == 12.5


async def test_last_session_migrates_from_the_old_state_only_path(hass, clock, monkeypatch):
    """Installs upgrading from the state-only scheme have no payload yet."""
    sensor, _ = _last_session()
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_last_session_energy"
    monkeypatch.setattr(
        sensor, "async_get_last_state",
        AsyncMock(return_value=State(sensor.entity_id, "7.25")),
    )

    await sensor.async_added_to_hass()

    assert sensor.native_value == 7.25


async def test_last_session_ignores_a_corrupted_payload(hass, clock):
    sensor, _ = _last_session()
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_last_session_energy"
    mock_restore_cache_with_extra_data(
        hass,
        ((State(sensor.entity_id, STATE_UNAVAILABLE), {"computed": "unknown"}),),
    )

    await sensor.async_added_to_hass()

    assert sensor.native_value is None


async def test_daily_energy_migrates_from_legacy_attributes(hass, clock, monkeypatch):
    """No install has a payload until it shuts down once on this version.

    Without this one-time fallback the fix would reproduce the very bug it fixes,
    exactly once, for every upgrading user.
    """
    sensor, coord = _make(DailyEnergySensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_daily_energy"
    today = _DAY.date().isoformat()
    # Nothing in the extra-data cache — pre-upgrade installs only have attributes.
    monkeypatch.setattr(
        sensor, "async_get_last_state",
        AsyncMock(return_value=State(sensor.entity_id, "5.0",
                                     {"date": today, "baseline_kwh": 100.0})),
    )

    await sensor.async_added_to_hass()

    assert sensor._baseline == 100.0
    assert sensor._computed == 5.0


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
