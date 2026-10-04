"""The restart gap, proved through the real setup path instead of a stub.

Every other test of this rule drives the sensor directly and hands it a gap
value. That proves "if the gap is X, the sensor does Y" and says nothing about
which X actually reaches the sensor — the hole that shipped the 2026-09-27
blocker, and then shipped it again one restore path over in v0.5.0.

Here nothing is hand-fed. The entry is set up the way Home Assistant sets it
up, which means the coordinator polls once inside async_setup_entry before the
platforms are forwarded, and the sensor's first callback therefore carries a
perfectly ordinary short gap however long Home Assistant was really down. The
sensor has to notice that from its own missing stamp.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import State
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.eveus.const import DOMAIN

_ENTITY = "sensor.smoke_daily_session_time"

# Ten hours of session, against a stored 100 s. If the downtime is billed, the
# sensor reads about ten hours; if it is not, it reads zero.
_PRE_GAP_SESSION_S = 100.0
_POST_GAP_SESSION_S = 36100.0


@pytest.fixture
def charging_station(monkeypatch):
    """A V2 that answers every poll, mid-charge, with the session well along."""
    async def _status(self):
        return {
            "sessionTime": _POST_GAP_SESSION_S,
            "totalEnergy": 54.9,
            "curMeas1": 16.0,
            "voltMeas1": 230.0,
            "state": 4,
        }

    monkeypatch.setattr(
        "custom_components.eveus.charger.v2.ChargerV2.get_status", _status
    )


async def _setup_with_stored(hass, stored: dict) -> MockConfigEntry:
    mock_restore_cache_with_extra_data(
        hass, ((State(_ENTITY, "0.0"), stored),)
    )
    return await _setup_without_stored(hass)


async def _setup_without_stored(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "1.2.3.4",
            "model": "v2",
            "username": "admin",
            "password": "secret",
            "device_prefix": "smoke",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll_again(hass, after: timedelta = timedelta(minutes=5)) -> None:
    """Drive one more coordinator refresh — the sensor's first observed frame.

    The wall clock moves far enough to trigger the scheduled refresh, but the
    coordinator sizes its gap from monotonic time, which barely moves here.
    That mismatch is the point: the coordinator honestly reports a short gap
    while a long stretch of wall time went unobserved, exactly as it does
    after a restart.
    """
    async_fire_time_changed(hass, dt_util.utcnow() + after)
    await hass.async_block_till_done()


async def test_an_upgrade_restore_does_not_bill_the_downtime(hass, charging_station):
    """Storage written before 0.5.0: prev_s, and no stamp to size the gap with.

    These three keys are the whole of the pre-0.5.0 payload — `incomplete` and
    `prev_stamp` were both introduced by 0.5.0 itself, so a fixture carrying
    them describes a version that never existed.
    """
    await _setup_with_stored(
        hass,
        {
            "date": dt_util.now().date().isoformat(),
            "accumulated_s": 0.0,
            "prev_s": _PRE_GAP_SESSION_S,
        },
    )

    await _poll_again(hass)

    state = hass.states.get(_ENTITY)
    assert state is not None
    assert float(state.state) == 0.0, (
        "ten hours of downtime is not charging time, however short the "
        "coordinator's own gap looks on the first frame after a restart"
    )
    assert state.attributes["day_incomplete"] is True


async def test_a_restore_of_yesterday_leaves_the_day_flagged(hass, charging_station):
    """Home Assistant down from last night into this morning.

    The payload is yesterday's, so nothing of it is carried into today — but
    its stamp still says when this sensor last saw anything, and that is what
    makes the unwatched morning visible. Reading the stamp only after the date
    check threw it away, and the first frame then cleared the flag on a day
    whose first hours nobody observed.
    """
    stamp = (dt_util.utcnow() - timedelta(hours=10)).isoformat()
    yesterday = (dt_util.now().date() - timedelta(days=1)).isoformat()
    await _setup_with_stored(
        hass,
        {
            "date": yesterday,
            "accumulated_s": 7200.0,
            "prev_s": _PRE_GAP_SESSION_S,
            "incomplete": False,
            "prev_total": 50.0,
            "prev_stamp": stamp,
        },
    )

    await _poll_again(hass)

    state = hass.states.get(_ENTITY)
    assert state is not None
    assert float(state.state) == 0.0, "yesterday's total must not carry over"
    assert state.attributes["day_incomplete"] is True, (
        "ten unwatched hours of this day must not read as a day fully observed"
    )


async def test_a_sensor_with_nothing_stored_does_not_claim_the_day(
    hass, charging_station
):
    """No payload at all is not evidence that nothing was missed.

    The first version of this fix made an exception here, reasoning that a new
    sensor has no earlier observation of its own to be missing. That is the
    same mislabel one case over: the coordinator's gap measures the
    COORDINATOR's blindness, never this sensor's coverage of the day. A review
    pass caught it.

    Two real ways to arrive here with hours of the day genuinely unobserved:
    RestoreEntity drops stored state after seven days, and an entity added —
    or removed and re-added — at midday has no claim on the morning.
    """
    # No restore cache seeded at all: async_get_last_extra_data and
    # async_get_last_state both come back empty, which is the genuine
    # fresh-entity path. Seeding an empty payload would instead exercise the
    # corrupt-payload branch, which returns a few lines earlier.
    await _setup_without_stored(hass)

    await _poll_again(hass)

    state = hass.states.get(_ENTITY)
    assert state is not None
    assert state.attributes["day_incomplete"] is True, (
        "a sensor that cannot show it was watching must not say the day was"
    )


async def test_a_brief_restart_across_midnight_leaves_the_day_complete(
    hass, charging_station
):
    """The other direction, and the one that needs the stamp to survive.

    Home Assistant restarted just before midnight and was back half a minute
    later: nothing of the new day went unobserved, so the day is complete. The
    only thing that can say so is yesterday's stamp, because the day it was
    written on is not today — and the restore used to throw it away on exactly
    that grounds, leaving the sensor unable to tell this apart from being down
    all night.

    Without it the flag errs the safe way rather than the dangerous one, which
    is why the previous test still passes without this fix and this one does
    not: a day wrongly called incomplete costs trust in the flag, not data.
    """
    stamp = (dt_util.utcnow() - timedelta(seconds=30)).isoformat()
    yesterday = (dt_util.now().date() - timedelta(days=1)).isoformat()
    await _setup_with_stored(
        hass,
        {
            "date": yesterday,
            "accumulated_s": 7200.0,
            "prev_s": _PRE_GAP_SESSION_S,
            "incomplete": False,
            "prev_total": 50.0,
            "prev_stamp": stamp,
        },
    )

    await _poll_again(hass, after=timedelta(seconds=31))

    state = hass.states.get(_ENTITY)
    assert state is not None
    assert state.attributes["day_incomplete"] is False, (
        "a 30 s restart observed from both sides leaves nothing unwatched"
    )
