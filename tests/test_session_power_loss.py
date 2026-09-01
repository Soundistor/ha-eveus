"""A session cut short by a power loss must still be reported.

Measured on V2 2026-09-01: the owner pulled power mid-charge. The station boots
straight back into charging, so `_prev_state` was "charging" before and after
and `session_transition` returned None — nothing latched. Worse, the first
frame back carries the new session's zero, which used to overwrite the live
figures before anything could read them. 12.901 kWh disappeared, and the UI kept
showing a plausible 9.102 from a session two hours older.

The rule: sessionEnergy back at exactly zero while the state is still active.
Everything here is a criterion from the backlog item, including the ones that
pin what must NOT latch.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
import pytest

from custom_components.eveus.const import (
    EVENT_CHARGING_STARTED,
    EVENT_SESSION_ENDED,
)
from custom_components.eveus.coordinator import STALE_STATE_AFTER

from .test_coordinator import _ENTRY_ID, _make_coordinator, _poll_ok


@pytest.fixture(name="events")
def events_fixture(hass):
    """Collect both session events in the order they are fired."""
    seen: list[tuple[str, dict]] = []
    for name in (EVENT_SESSION_ENDED, EVENT_CHARGING_STARTED):
        hass.bus.async_listen(name, lambda e: seen.append((e.event_type, dict(e.data))))
    return seen


async def _fired(hass, events, name):
    await hass.async_block_till_done()
    return [data for event_type, data in events if event_type == name]


async def test_a_power_cut_mid_charge_still_reports_the_session(hass, events):
    """Criterion 1 — the measured scenario, end to end."""
    coord = _make_coordinator(hass)
    await _poll_ok(coord, state="charging", sessionEnergy=12.9, sessionTime=3600)

    coord.charger.set_exc(TimeoutError("station lost power"))
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()

    await _poll_ok(coord, state="charging", sessionEnergy=0, sessionTime=0)

    ended = await _fired(hass, events, EVENT_SESSION_ENDED)
    assert len(ended) == 1
    assert ended[0]["energy_kwh"] == 12.9, "the interrupted session, not the new zero"
    assert ended[0]["duration_s"] == 3600
    assert ended[0]["ended_state"] == "charging", (
        "we genuinely do not know which state the station died in"
    )
    assert coord.last_session["energy_kwh"] == 12.9

    started = await _fired(hass, events, EVENT_CHARGING_STARTED)
    assert len(started) == 1, "the new session must not be silent"
    assert coord._live_energy == 0, "a new session is running, not absent"


async def test_a_power_cycle_between_two_polls_latches_the_same_way(hass, events):
    """Criterion 2 — no failed poll in between.

    Power can come back inside the 30 s interval, and the same shape also covers
    a car unplugged and replugged between polls (charging -> standby ->
    charging, seen from here as charging -> charging with a zero). Requiring an
    unreachable poll would narrow the fix to one of its causes.
    """
    coord = _make_coordinator(hass)
    await _poll_ok(coord, state="charging", sessionEnergy=12.9)
    await _poll_ok(coord, state="charging", sessionEnergy=0)

    ended = await _fired(hass, events, EVENT_SESSION_ENDED)
    assert len(ended) == 1
    assert ended[0]["energy_kwh"] == 12.9


async def test_a_reboot_out_of_paused_fires_charging_started_exactly_once(hass, events):
    """Criterion 3 — the latch and the ordinary transition overlap here.

    paused -> charging is already a charging_started; the latch fires one too.
    Firing both would break the started/ended pairing this fix exists to keep.
    """
    coord = _make_coordinator(hass)
    await _poll_ok(coord, state="paused", sessionEnergy=12.9)
    await _poll_ok(coord, state="charging", sessionEnergy=0)

    assert len(await _fired(hass, events, EVENT_SESSION_ENDED)) == 1
    started = await _fired(hass, events, EVENT_CHARGING_STARTED)
    assert len(started) == 1, "one boundary, one start"


async def test_a_first_session_starting_from_zero_does_not_latch(hass, events):
    """Criterion 4 — and the reason the guard is `is not None`, not just `> 0`.

    _live_energy is None at start and returns to None after every ordinary
    session end, so a bare `_live_energy > 0` would raise TypeError on the most
    common event in the device's life — a charge beginning — and the broad
    except would turn it into a repair issue with every entity unavailable.
    """
    coord = _make_coordinator(hass)

    await _poll_ok(coord, state="charging", sessionEnergy=0)

    assert not await _fired(hass, events, EVENT_SESSION_ENDED)
    assert coord.last_session is None
    assert coord.last_update_success
    assert not ir.async_get(hass).async_get_issue("eveus", f"device_error_{_ENTRY_ID}")


async def test_a_second_zero_in_a_row_does_not_latch_again(hass, events):
    """Criterion 5 — the latch must not repeat every poll of a young session."""
    coord = _make_coordinator(hass)
    await _poll_ok(coord, state="charging", sessionEnergy=12.9)
    await _poll_ok(coord, state="charging", sessionEnergy=0)
    await _poll_ok(coord, state="charging", sessionEnergy=0)

    assert len(await _fired(hass, events, EVENT_SESSION_ENDED)) == 1


async def test_a_small_rollback_is_not_a_session_boundary(hass, events):
    """Criterion 6 — why the rule is exactly zero and not "any drop".

    totalEnergy was measured rolling back 0.5 kWh live (2026-08-18). Treating
    any decrease as a boundary would need an answer to "can the station lower
    sessionEnergy mid-session", which nobody has; exactly-zero does not.
    """
    coord = _make_coordinator(hass)
    await _poll_ok(coord, state="charging", sessionEnergy=12.9)
    await _poll_ok(coord, state="charging", sessionEnergy=12.4)

    assert not await _fired(hass, events, EVENT_SESSION_ENDED)
    assert coord._live_energy == 12.4


async def test_the_latch_is_not_subject_to_the_stale_baseline_window(hass, events):
    """Criterion 7 — deliberately unlike the state baseline.

    A gap over STALE_STATE_AFTER drops _prev_state so a stale *transition* is
    not replayed. Energy is not stale in that sense: kWh already delivered stay
    true two days later. Subordinating the latch would cut out the very case the
    item exists for, since a station left unpowered easily exceeds 15 minutes.
    """
    coord = _make_coordinator(hass)
    await _poll_ok(coord, state="charging", sessionEnergy=12.9)

    coord._last_success = dt_util.utcnow() - STALE_STATE_AFTER - timedelta(minutes=1)
    await _poll_ok(coord, state="charging", sessionEnergy=0)

    ended = await _fired(hass, events, EVENT_SESSION_ENDED)
    assert len(ended) == 1
    assert ended[0]["energy_kwh"] == 12.9


async def test_an_ordinary_finish_is_untouched(hass, events):
    """Criterion 8 — the measured-good path must not move.

    The command stop at 07:29:56 on 2026-09-01 recorded 9.102 correctly; that
    is the branch this fix must not disturb.
    """
    coord = _make_coordinator(hass)
    await _poll_ok(coord, state="charging", sessionEnergy=9.102, sessionTime=1800)
    await _poll_ok(coord, state="standby", sessionEnergy=0)

    ended = await _fired(hass, events, EVENT_SESSION_ENDED)
    assert len(ended) == 1
    assert ended[0]["energy_kwh"] == 9.102
    assert ended[0]["ended_state"] == "standby"
    assert coord._live_energy is None, "no session is running now"


async def test_a_garbage_counter_neither_latches_nor_breaks_the_poll(hass, events):
    """V2 passes sessionEnergy through untouched, so the stored value is the one
    that must be numeric by construction — otherwise the comparison raises on
    the *next* poll, not this one."""
    coord = _make_coordinator(hass)
    await _poll_ok(coord, state="charging", sessionEnergy="not-a-number")
    await _poll_ok(coord, state="charging", sessionEnergy=0)

    assert not await _fired(hass, events, EVENT_SESSION_ENDED)
    assert coord.last_update_success
