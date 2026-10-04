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
        # Mirrors the real coordinator's gap primitive. Defaults describe a
        # normally polled frame, so a test that says nothing about the gap is
        # a test about something else.
        self.gap_s: float | None = 30.0
        self.frame_time = None

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


_BUILT: list = []


@pytest.fixture(autouse=True)
def _remove_entities():
    """Tear entities down the way HA does when the entry unloads.

    The daily sensors register a midnight timer through async_on_remove, and
    async_added_to_hass is called directly here without anything ever removing
    the entity — so the timer outlives the test and pytest-homeassistant fails
    the teardown on a lingering timer.
    """
    _BUILT.clear()
    yield
    for entity in _BUILT:
        entity._call_on_remove_callbacks()
    _BUILT.clear()


def _make(cls):
    coord = _Coord()
    entity = cls(coord, _Charger(), "smoke", "e1")
    entity.async_write_ha_state = lambda: None  # bypass HA state plumbing
    _BUILT.append(entity)
    return entity, coord


def _update(entity, coord, gap_s=30.0, frame_time=None, **data):
    coord.data = data
    coord.gap_s = gap_s
    coord.frame_time = frame_time
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


def test_daily_energy_small_rollback_that_stays_above_the_baseline(clock):
    """Measured live 2026-08-18: totalEnergy came back 0.5 kWh lower (272.5 after
    273.0). That is NOT the counter reset the two tests above cover — it never
    crosses the baseline, so the rebase branch (sensor.py) is not entered at all.

    Pins the current behaviour: a transient dip of exactly the rollback, then a
    clean recovery. Never negative, never a jump.
    """
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=250.0)    # baseline for the day
    _update(sensor, coord, totalEnergy=273.0)
    assert sensor.native_value == 23.0
    baseline = sensor._baseline

    _update(sensor, coord, totalEnergy=272.5)    # the live rollback
    assert sensor.native_value == 22.5, "the dip is the rollback, nothing more"
    assert sensor._baseline == baseline, "no rebase — the baseline was never crossed"

    _update(sensor, coord, totalEnergy=273.2)
    assert sensor.native_value == 23.2, "recovers on the next healthy frame"


def test_daily_energy_small_rollback_that_dips_under_the_baseline(clock):
    """The same rollback early in the day, when it is bigger than what the day
    has accumulated — so it DOES cross the baseline and takes the rebase branch
    written for a full counter reset.

    Pins the current behaviour rather than asserting a desired one: the day
    never goes negative and never freezes, but the rebase treats the rollback as
    a reset and the day keeps the 0.3 kWh it never earned. That over-count is a
    separate finding, not this item's fix.
    """
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)    # baseline for the day
    _update(sensor, coord, totalEnergy=100.2)
    assert sensor.native_value == 0.2

    _update(sensor, coord, totalEnergy=99.9)     # rollback of 0.3, day had 0.2
    assert sensor.native_value == 0.2, "the day holds, it must not go negative"
    assert sensor._baseline == 99.7

    _update(sensor, coord, totalEnergy=100.4)
    # True gain since the day started is 0.4 (100.0 -> 100.4). The rebase has
    # folded the 0.3 rollback into the day.
    assert sensor.native_value == 0.7


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
    _update(sensor, coord, sessionTime=100, curMeas1=16.0)   # baseline this day
    _update(sensor, coord, sessionTime=3700, curMeas1=16.0)  # +3600s = 1h
    assert sensor.native_value == 1.0
    _update(sensor, coord, sessionTime=3700, curMeas1=16.0)  # no change
    assert sensor.native_value == 1.0


def test_daily_session_time_new_session_negative_delta(clock):
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, curMeas1=16.0)
    _update(sensor, coord, sessionTime=3700, curMeas1=16.0)  # +3600 -> 1h
    # new session (reset) -> negative delta ignored
    _update(sensor, coord, sessionTime=30, curMeas1=16.0)
    assert sensor._accumulated == 3600.0
    _update(sensor, coord, sessionTime=1830, curMeas1=16.0)  # +1800 from the new session
    assert sensor._accumulated == 5400.0
    assert sensor.native_value == 1.5


def test_daily_session_time_cross_midnight_split(clock):
    sensor, coord = _make(DailySessionTimeSensor)
    # session starts, baseline
    _update(sensor, coord, sessionTime=0, curMeas1=16.0)
    _update(sensor, coord, sessionTime=3600, curMeas1=16.0)  # +1h on day D
    assert sensor.native_value == 1.0

    clock["now"] = _NEXT_DAY
    # rollover: reset, prev re-anchored
    _update(sensor, coord, sessionTime=7200, curMeas1=16.0)
    assert sensor.native_value == 0.0
    _update(sensor, coord, sessionTime=9000, curMeas1=16.0)  # +1800s = 0.5h on day D+1
    assert sensor.native_value == 0.5
    assert sensor._current_date == _NEXT_DAY.date()


# The gate: sessionTime is session duration, not charging time. Measured
# 2026-09-22 under a time limit (.claude/ralph/timelimit-v2-2026-09-22.log:13-20)
# — state=5, curMeas1=0, counter running 1:1 while sessionEnergy stayed frozen.

def test_daily_session_time_ignores_a_standing_car_in_charge_complete(clock):
    """The 2026-09-20 shape: state=5, zero current, counter still climbing."""
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=12249, curMeas1=16.0, state=4)
    _update(sensor, coord, sessionTime=13929, curMeas1=0, state=5)
    assert sensor._accumulated == 0.0, "1680 s of standing must not count as charging"
    # prev still moved, so the next charging frame bills only its own interval
    _update(sensor, coord, sessionTime=14529, curMeas1=16.0, state=4)
    assert sensor._accumulated == 600.0


def test_daily_session_time_ignores_zero_current_inside_state_4(clock):
    """The same defect without a terminal state — the gate cannot be on state."""
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=1220, curMeas1=16.0, state=4)
    _update(sensor, coord, sessionTime=1264, curMeas1=0, state=4)
    assert sensor._accumulated == 0.0


def test_daily_session_time_skips_a_frame_without_a_current_reading(clock):
    """Unknown is not the same as flowing: no reading, no delta."""
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, curMeas1=16.0)
    _update(sensor, coord, sessionTime=200)               # key absent
    assert sensor._accumulated == 0.0
    _update(sensor, coord, sessionTime=300, curMeas1=None)  # present but null
    assert sensor._accumulated == 0.0
    _update(sensor, coord, sessionTime=400, curMeas1=float("nan"))
    assert sensor._accumulated == 0.0
    # every one of those frames still moved _prev
    assert sensor._prev == 400
    _update(sensor, coord, sessionTime=500, curMeas1=16.0)
    assert sensor._accumulated == 100.0


def test_daily_session_time_current_drops_to_zero_within_one_sample(clock):
    """Why the threshold is strictly > 0 and not a small number.

    In the measured transition curMeas1 and powerMeas both reached 0 in a
    single sample, so there is no intermediate band to tolerate.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=1000, curMeas1=9.6)
    _update(sensor, coord, sessionTime=1030, curMeas1=9.6)
    assert sensor._accumulated == 30.0
    _update(sensor, coord, sessionTime=1060, curMeas1=0)
    assert sensor._accumulated == 30.0, "the interval ending at zero amps is not charging"


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


# --------------------------------------------------------------------------- #
# Midnight rollover on a timer
#
# The day boundary used to arrive on the first successful poll after midnight.
# The charger is powered only while a car is plugged in, so on a day with no
# charging it never arrived: measured 2026-09-20..22, the sensor showed 33.761
# kWh all through a day with no session.
# --------------------------------------------------------------------------- #

def test_daily_energy_timer_rollover_zeroes_the_day(clock):
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)
    _update(sensor, coord, totalEnergy=108.0)
    assert sensor.native_value == 8.0

    clock["now"] = _NEXT_DAY
    sensor._roll_over_at_midnight(None)

    assert sensor.native_value == 0.0, "a new day starts at zero, not at unknown"
    assert sensor._current_date == _NEXT_DAY.date()


def test_daily_energy_timer_rollover_moves_last_reset_with_the_value(clock):
    """Zeroing a TOTAL sensor without moving last_reset corrupts the long-term sum.

    The recorder would read a fall with no reset and subtract yesterday's whole
    figure from `sum`.
    """
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)
    _update(sensor, coord, totalEnergy=108.0)
    before = sensor._attr_last_reset

    clock["now"] = _NEXT_DAY
    sensor._roll_over_at_midnight(None)

    assert sensor._attr_last_reset != before
    assert sensor._attr_last_reset == dt_util.start_of_local_day(_NEXT_DAY)


def test_daily_energy_timer_rollover_does_not_carry_yesterday_over(clock):
    """The trap: leaving _computed set sends the next frame into the rebase branch.

    baseline would become total - yesterday, and the new day would open already
    holding yesterday's kWh.
    """
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)
    _update(sensor, coord, totalEnergy=108.0)

    clock["now"] = _NEXT_DAY
    sensor._roll_over_at_midnight(None)
    _update(sensor, coord, totalEnergy=108.0)   # first frame of the new day

    assert sensor.native_value == 0.0, "yesterday's 8 kWh must not reappear"
    _update(sensor, coord, totalEnergy=110.5)
    assert sensor.native_value == 2.5


def test_daily_session_time_timer_rollover_drops_prev(clock):
    """Keeping _prev bills the whole unobserved night as charging time."""
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, curMeas1=16.0)
    _update(sensor, coord, sessionTime=3700, curMeas1=16.0)
    assert sensor.native_value == 1.0

    clock["now"] = _NEXT_DAY
    sensor._roll_over_at_midnight(None)
    assert sensor._prev is None

    # A session that ran all night: the counter is far ahead of last night's
    # position, and that distance is not today's charging time.
    _update(sensor, coord, sessionTime=40000, curMeas1=16.0)
    assert sensor.native_value == 0.0
    _update(sensor, coord, sessionTime=41800, curMeas1=16.0)
    assert sensor.native_value == 0.5


def test_a_day_with_no_frames_at_all_reads_zero(clock):
    """Symptom 3: the charger is unplugged and powered off for a whole day."""
    sensor, coord = _make(DailyEnergySensor)
    _update(sensor, coord, totalEnergy=100.0)
    _update(sensor, coord, totalEnergy=133.761)
    assert sensor.native_value == 33.761

    clock["now"] = _NEXT_DAY
    sensor._roll_over_at_midnight(None)   # no frame arrives all day

    assert sensor.native_value == 0.0, "yesterday's total must not stand in for today"


@pytest.mark.parametrize("cls", [DailyEnergySensor, DailySessionTimeSensor])
def test_timer_rollover_publishes_the_state(clock, cls):
    """Without an explicit write the zero waits for a frame that never comes."""
    sensor, coord = _make(cls)
    writes = []
    sensor.async_write_ha_state = lambda: writes.append(1)

    clock["now"] = _NEXT_DAY
    sensor._roll_over_at_midnight(None)

    assert writes, "the timer must publish; on an idle day nothing else will"


@pytest.mark.parametrize("cls", [DailyEnergySensor, DailySessionTimeSensor])
async def test_midnight_timer_is_registered_and_removable(hass, clock, cls):
    """The timer is added to the frame path, not substituted for it.

    After an HA restart past midnight there is no timer yet, and the frame
    rollover — which the tests above still exercise — is what covers that.
    """
    sensor, coord = _make(cls)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_smoke"

    await sensor.async_added_to_hass()

    assert sensor._on_remove, "async_added_to_hass registered the midnight timer"


# --------------------------------------------------------------------------- #
# The incompleteness flag
#
# The value says what the integration observed; the flag says whether that was
# the whole day. The two sensors judge it by DIFFERENT criteria, on purpose:
# energy can only lose at the day's start, time loses wherever the gap falls.
# --------------------------------------------------------------------------- #

def _midnight():
    """Local midnight of the day the patched clock is on.

    Built at CALL time on purpose. _DAY is created at import, when
    DEFAULT_TIME_ZONE is still UTC, while the suite later runs under
    US/Pacific — so a midnight derived from _DAY sits seven hours away from
    the one the sensor compares against.
    """
    return dt_util.start_of_local_day()


def test_daily_energy_is_complete_when_the_baseline_is_taken_at_midnight(clock):
    sensor, coord = _make(DailyEnergySensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)
    assert sensor.extra_state_attributes["day_incomplete"] is True, "starts unobserved"

    _update(sensor, coord, totalEnergy=100.0,
            frame_time=_midnight() + timedelta(seconds=30))

    assert sensor.extra_state_attributes["day_incomplete"] is False


def test_daily_energy_is_incomplete_when_the_baseline_is_taken_hours_late(clock):
    """The measured case: the station was dark until 09:40."""
    sensor, coord = _make(DailyEnergySensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)

    _update(sensor, coord, totalEnergy=100.0,
            frame_time=_midnight() + timedelta(hours=9, minutes=40))

    assert sensor.extra_state_attributes["day_incomplete"] is True


def test_daily_energy_counts_a_baseline_from_just_before_midnight_as_complete(clock):
    """A stale pre-midnight frame is a BETTER baseline than a late one.

    Judging lateness only would mark the better outcome as the worse one.
    """
    sensor, coord = _make(DailyEnergySensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)

    _update(sensor, coord, totalEnergy=100.0,
            frame_time=_midnight() - timedelta(seconds=90))

    assert sensor.extra_state_attributes["day_incomplete"] is False


def test_a_gap_that_ends_just_after_midnight_leaves_the_day_complete(clock):
    """A night-long gap costs this day only the part of it after midnight.

    The station went offline at 20:00 and came back at 00:00:30. Four hours
    were unwatched, but thirty seconds of them were THIS day's, and the rest
    belongs to yesterday, which has its own verdict. The docstring on
    _judge_gap promised this; the code judged the whole gap and marked the day
    incomplete.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)

    _update(sensor, coord, sessionTime=100, curMeas1=16.0,
            gap_s=4 * 3600, frame_time=_midnight() + timedelta(seconds=30))

    assert sensor.extra_state_attributes["day_incomplete"] is False


def test_the_same_gap_ending_later_in_the_morning_does_not(clock):
    """The other side of the clip: ten minutes in, ten minutes were missed."""
    sensor, coord = _make(DailySessionTimeSensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)

    _update(sensor, coord, sessionTime=100, curMeas1=16.0,
            gap_s=4 * 3600, frame_time=_midnight() + timedelta(minutes=10))

    assert sensor.extra_state_attributes["day_incomplete"] is True


def test_an_unknown_gap_is_clipped_by_the_day_boundary_too(clock):
    """Nothing persisted, and the first frame lands 30 s into the day.

    "Unknown gap" normally reads as unobserved, but the bound is a fact about
    the day rather than about what this sensor remembers: at 00:00:30 at most
    thirty seconds of today can have been missed, whatever the sensor knows.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)

    _update(sensor, coord, sessionTime=100, curMeas1=16.0,
            gap_s=None, frame_time=_midnight() + timedelta(seconds=30))

    assert sensor.extra_state_attributes["day_incomplete"] is False


def test_an_unknown_gap_mid_day_still_reads_as_unobserved(clock):
    """The clip must not turn "cannot know" into "nothing happened"."""
    sensor, coord = _make(DailySessionTimeSensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)

    _update(sensor, coord, sessionTime=100, curMeas1=16.0,
            gap_s=None, frame_time=_midnight() + timedelta(hours=9))

    assert sensor.extra_state_attributes["day_incomplete"] is True


def test_a_web_ui_counter_reset_does_not_mark_the_day_incomplete(clock):
    """The other way into the rebase branch — and the day was watched throughout."""
    sensor, coord = _make(DailyEnergySensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)
    _update(sensor, coord, totalEnergy=100.0, frame_time=_midnight())
    _update(sensor, coord, totalEnergy=104.0, frame_time=_midnight())
    assert sensor.extra_state_attributes["day_incomplete"] is False

    # rstEM2 in the station's web UI: the lifetime total drops below baseline
    _update(sensor, coord, totalEnergy=0.5,
            frame_time=_midnight() + timedelta(hours=6))

    assert sensor.extra_state_attributes["day_incomplete"] is False
    assert sensor.native_value == 4.0, "the day's accumulation survives the reset"


def test_daily_session_time_is_complete_while_the_polling_is_unbroken(clock):
    sensor, coord = _make(DailySessionTimeSensor)
    clock["now"] = _DAY
    # A frame BEFORE the rollover, because that is what a sensor running into
    # midnight always has. Without it the sensor has no stamp, cannot size any
    # gap, and the unbroken polling this test is about never gets measured —
    # the stub would be asserting on a sensor production never produces.
    _update(sensor, coord, sessionTime=70, curMeas1=16.0, gap_s=30.0)
    sensor._roll_over_at_midnight(None)

    _update(sensor, coord, sessionTime=100, curMeas1=16.0, gap_s=30.0)

    assert sensor.extra_state_attributes["day_incomplete"] is False


def test_daily_session_time_is_incomplete_after_an_unwatched_stretch(clock):
    """And it stays incomplete: a tidy afternoon does not erase a quiet hour."""
    sensor, coord = _make(DailySessionTimeSensor)
    clock["now"] = _DAY
    _update(sensor, coord, sessionTime=70, curMeas1=16.0, gap_s=30.0)  # see above
    sensor._roll_over_at_midnight(None)
    _update(sensor, coord, sessionTime=100, curMeas1=16.0, gap_s=30.0)
    assert sensor.extra_state_attributes["day_incomplete"] is False

    _update(sensor, coord, sessionTime=3700, curMeas1=16.0, gap_s=3600.0)
    assert sensor.extra_state_attributes["day_incomplete"] is True

    _update(sensor, coord, sessionTime=3730, curMeas1=16.0, gap_s=30.0)
    assert sensor.extra_state_attributes["day_incomplete"] is True, "not lowered later"


def test_an_unknown_gap_reads_as_unobserved_not_as_observed(clock):
    """gap_s is None on the coordinator's first poll after a start.

    "We cannot know what happened before this" is not "nothing happened".
    """
    sensor, coord = _make(DailySessionTimeSensor)
    clock["now"] = _DAY
    sensor._roll_over_at_midnight(None)

    _update(sensor, coord, sessionTime=100, curMeas1=16.0, gap_s=None)

    assert sensor.extra_state_attributes["day_incomplete"] is True


@pytest.mark.parametrize("cls", [DailyEnergySensor, DailySessionTimeSensor])
def test_a_day_with_no_frames_reads_zero_and_says_it_is_incomplete(clock, cls):
    """The pairing is the point: 0 alone would be a lie told confidently."""
    sensor, coord = _make(cls)
    clock["now"] = _NEXT_DAY
    sensor._roll_over_at_midnight(None)

    assert sensor.native_value == 0.0
    assert sensor.extra_state_attributes["day_incomplete"] is True


# --------------------------------------------------------------------------- #
# Counting a delta across an interval nobody watched
#
# Owner's decision: count it if — and only if — totalEnergy moved across the
# gap. Not moved means the station charged nothing, which is a station-side
# fact rather than an inference. Moved means charging happened, and discarding
# legitimate time is the worse error.
# --------------------------------------------------------------------------- #

def test_a_gap_with_no_charging_does_not_count(clock):
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, totalEnergy=50.0, curMeas1=16.0)

    # HA was down for an hour; the station stood idle throughout
    _update(sensor, coord, sessionTime=3700, totalEnergy=50.0, curMeas1=16.0,
            gap_s=3600.0)

    assert sensor._accumulated == 0.0


def test_a_gap_with_charging_counts_whole(clock):
    """The named price: part-charged, part-stood counts entirely."""
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, totalEnergy=50.0, curMeas1=16.0)

    _update(sensor, coord, sessionTime=3700, totalEnergy=54.9, curMeas1=16.0,
            gap_s=3600.0)

    assert sensor._accumulated == 3600.0


def test_a_v1_power_cut_rolling_the_counter_back_is_not_charging(clock):
    """Measured 2026-09-27: V1 reverts totalEnergy to its session-start value.

    An inequality against zero would read that lost tail as charging.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=500, totalEnergy=219.1, curMeas1=16.0)

    _update(sensor, coord, sessionTime=3700, totalEnergy=218.6, curMeas1=16.0,
            gap_s=3600.0)

    assert sensor._accumulated == 0.0


def test_quantisation_noise_does_not_open_the_gate(clock):
    """The floor is 0.0005 on V2, 0.0000 on V1 (KB-02 §1.1.6)."""
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, totalEnergy=4438.5542, curMeas1=16.0)

    _update(sensor, coord, sessionTime=3700, totalEnergy=4438.5547, curMeas1=16.0,
            gap_s=3600.0)

    assert sensor._accumulated == 0.0


def test_the_current_gate_is_not_applied_to_a_gap_delta(clock):
    """Stacking both gates drops every gap delta — the rejected variant.

    This frame's curMeas1 describes this instant and says nothing about the
    minutes nobody watched.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, totalEnergy=50.0, curMeas1=16.0)

    # charging happened in the gap, but the car has since stopped
    _update(sensor, coord, sessionTime=3700, totalEnergy=54.9, curMeas1=0,
            gap_s=3600.0)

    assert sensor._accumulated == 3600.0


def test_a_gap_frame_without_total_energy_drops_the_delta(clock):
    """Conservative on purpose — see the commit message.

    The counter guard strips totalEnergy for two polls, and V1's post-reboot
    frame carries none. Without a reading there is no station-side fact, and a
    false positive costs far more than a miss.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, totalEnergy=50.0, curMeas1=16.0)

    _update(sensor, coord, sessionTime=3700, curMeas1=16.0, gap_s=3600.0)

    assert sensor._accumulated == 0.0
    assert sensor.extra_state_attributes["day_incomplete"] is True


def test_the_snapshot_comes_from_one_frame(clock):
    """A frame stripped of totalEnergy clears the anchor, not just ages it.

    Otherwise a stale total pairs with a fresh sessionTime and the Delta spans
    a longer window than the gap — opening the gate for a gap in which nothing
    charged.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    _update(sensor, coord, sessionTime=100, totalEnergy=50.0, curMeas1=16.0)
    _update(sensor, coord, sessionTime=130, curMeas1=16.0)   # guard stripped it
    assert sensor._prev_total is None
    watched = sensor._accumulated   # the 30 s before the gap, counted normally

    _update(sensor, coord, sessionTime=3730, totalEnergy=54.9, curMeas1=16.0,
            gap_s=3600.0)

    assert sensor._accumulated == watched, "no anchor, no verdict on the gap"


async def test_the_sensors_own_stamp_beats_the_coordinators_gap_after_a_restart(
    hass, clock
):
    """The blocker this rule nearly shipped with.

    async_setup_entry awaits the coordinator's first refresh BEFORE forwarding
    the platforms, so by the time the sensor sees a frame the coordinator has
    already paired it with its own predecessor and reports an ordinary 60 s.
    Trusting that makes a half-hour HA outage invisible — in the one scenario
    the whole rule was written for.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_smoke"
    long_ago = dt_util.utcnow() - timedelta(minutes=25)
    mock_restore_cache_with_extra_data(
        hass,
        ((State(sensor.entity_id, STATE_UNAVAILABLE),
          {"date": _DAY.date().isoformat(), "accumulated_s": 0.0, "prev_s": 100.0,
           "incomplete": False, "prev_total": 50.0,
           "prev_stamp": long_ago.isoformat()}),),
    )
    await sensor.async_added_to_hass()

    # The coordinator polled once before the platforms were forwarded, so it
    # reports a perfectly ordinary gap. The station charged nothing meanwhile.
    _update(sensor, coord, sessionTime=1600, totalEnergy=50.0, curMeas1=16.0,
            gap_s=60.0, frame_time=dt_util.utcnow())

    assert sensor._accumulated == 0.0, "25 minutes of HA downtime is not charging time"
    assert sensor.extra_state_attributes["day_incomplete"] is True


async def test_a_failure_notification_is_not_read_as_a_frame(hass, clock):
    """HA calls listeners on success->failure with the stale frame still in place.

    Judging it would lower the incompleteness flag on a day whose first real
    frame has not arrived, using yesterday's reading as the evidence.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    clock["now"] = _NEXT_DAY
    sensor._roll_over_at_midnight(None)
    assert sensor.extra_state_attributes["day_incomplete"] is True

    coord.last_update_success = False
    _update(sensor, coord, sessionTime=3700, totalEnergy=50.0, curMeas1=16.0,
            gap_s=60.0)

    assert sensor.extra_state_attributes["day_incomplete"] is True, "still no frame today"
    assert sensor._prev_stamp is None, "a failure must not move the snapshot"


async def test_an_upgrade_restore_without_a_stamp_does_not_bill_the_downtime(hass, clock):
    """A restart where the coordinator's own first poll failed as well.

    gap_s is None whenever the first refresh after a start did not succeed —
    the station being offline at boot, which for these chargers is the normal
    case. Neither side can size the gap then, and that must read as unobserved
    rather than as nothing having happened.

    This is NOT the upgrade path, despite the name it was given: on an online
    start the coordinator polls before the platforms are forwarded and hands
    the sensor an ordinary gap instead. That path is proved in
    tests/test_restore_gap.py, through async_setup_entry, because it turns on
    which value actually arrives — something no hand-fed gap_s can show.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_smoke"
    mock_restore_cache_with_extra_data(
        hass,
        ((State(sensor.entity_id, STATE_UNAVAILABLE),
          # Three keys and no more: this is the whole pre-0.5.0 payload.
          # `incomplete` and `prev_stamp` were both introduced by 0.5.0, so a
          # fixture carrying either describes a version that never shipped.
          {"date": _DAY.date().isoformat(), "accumulated_s": 0.0,
           "prev_s": 100.0}),),
    )
    await sensor.async_added_to_hass()
    assert sensor._prev == 100.0 and sensor._prev_stamp is None

    _update(sensor, coord, sessionTime=36100, totalEnergy=54.9, curMeas1=16.0,
            gap_s=None)

    assert sensor._accumulated == 0.0, "ten hours of downtime is not charging time"
    assert sensor.extra_state_attributes["day_incomplete"] is True


async def test_the_gap_is_sized_from_the_sensors_own_stamp_across_a_restart(
    hass, clock, monkeypatch
):
    """The coordinator cannot answer here — it keeps no state across a restart.

    This is the case the rule exists for, so the sensor uses its own stamp.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_smoke"
    long_ago = (dt_util.utcnow() - timedelta(hours=2)).isoformat()
    mock_restore_cache_with_extra_data(
        hass,
        ((State(sensor.entity_id, STATE_UNAVAILABLE),
          {"date": _DAY.date().isoformat(), "accumulated_s": 0.0, "prev_s": 100.0,
           "incomplete": False, "prev_total": 50.0, "prev_stamp": long_ago}),),
    )
    await sensor.async_added_to_hass()
    assert sensor._prev_total == 50.0

    # coordinator's first poll after the restart: it has no gap of its own
    _update(sensor, coord, sessionTime=7300, totalEnergy=54.9, curMeas1=16.0,
            gap_s=None)

    assert sensor._accumulated == 7200.0, "two hours of charging, seen by the counter"
    assert sensor.extra_state_attributes["day_incomplete"] is True


@pytest.mark.parametrize(
    "cls,stored",
    [
        (DailyEnergySensor,
         {"baseline_kwh": 100.0, "computed": 4.0, "incomplete": True}),
        (DailySessionTimeSensor,
         {"accumulated_s": 3600.0, "prev_s": 3700.0, "incomplete": True}),
    ],
)
async def test_the_flag_survives_a_restart_within_the_same_day(hass, clock, cls, stored):
    """Without persistence a restart silently relabels an incomplete day complete."""
    sensor, coord = _make(cls)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_smoke"
    mock_restore_cache_with_extra_data(
        hass,
        ((State(sensor.entity_id, STATE_UNAVAILABLE),
          {"date": _DAY.date().isoformat(), **stored}),),
    )

    await sensor.async_added_to_hass()

    assert sensor.extra_state_attributes["day_incomplete"] is True


async def test_a_restart_does_not_erase_a_quiet_hour(hass, clock):
    """The verdict on a day survives a restart in the middle of it.

    A payload written at 13:00 with the flag already raised by a quiet hour at
    noon, restored two minutes later. The gap is short, so if the sensor also
    believed this were the day's first frame it would LOWER the flag and call
    a day complete that had genuinely lost an hour. That is why
    _day_had_frame is persisted rather than assumed.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_smoke"
    mock_restore_cache_with_extra_data(
        hass,
        ((State(sensor.entity_id, STATE_UNAVAILABLE),
          {"date": _DAY.date().isoformat(), "accumulated_s": 3600.0,
           "prev_s": 3700.0, "incomplete": True, "day_had_frame": True,
           "prev_stamp": (dt_util.utcnow() - timedelta(minutes=2)).isoformat()}),),
    )
    await sensor.async_added_to_hass()

    _update(sensor, coord, sessionTime=3820, curMeas1=16.0, gap_s=120.0,
            frame_time=dt_util.utcnow())

    assert sensor.extra_state_attributes["day_incomplete"] is True


async def test_storage_without_the_key_defaults_to_the_safe_side(hass, clock):
    """Payloads written before this key existed must not clear a verdict.

    The same scenario, restored from storage that predates day_had_frame. The
    absent key has to read as True: False would let every upgrade erase
    whatever verdict the day had reached.
    """
    sensor, coord = _make(DailySessionTimeSensor)
    sensor.hass = hass
    sensor.entity_id = "sensor.eveus_smoke"
    mock_restore_cache_with_extra_data(
        hass,
        ((State(sensor.entity_id, STATE_UNAVAILABLE),
          {"date": _DAY.date().isoformat(), "accumulated_s": 3600.0,
           "prev_s": 3700.0, "incomplete": True,
           "prev_stamp": (dt_util.utcnow() - timedelta(minutes=2)).isoformat()}),),
    )
    await sensor.async_added_to_hass()
    assert sensor._day_had_frame is True

    _update(sensor, coord, sessionTime=3820, curMeas1=16.0, gap_s=120.0,
            frame_time=dt_util.utcnow())

    assert sensor.extra_state_attributes["day_incomplete"] is True


async def test_the_frame_flag_rides_in_the_persisted_payload(hass, clock):
    """It has to be written as well as read, or the restore has nothing."""
    sensor, _ = _make(DailySessionTimeSensor)
    sensor._day_had_frame = True
    assert sensor.extra_restore_state_data.as_dict()["day_had_frame"] is True
