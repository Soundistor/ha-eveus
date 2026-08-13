"""Coordinator tests: session events, the stale-baseline fix, error paths, interval.

Drives a real ChargerCoordinator over a fake charger (get_status returns a
prepared dict or raises; transform_data is identity), so each poll's resulting
`state`/counters are controlled directly. Time is simulated by nudging the
coordinator's internal `_last_success` rather than freezing the clock — the
stale-baseline logic only compares `utcnow() - _last_success` to
STALE_STATE_AFTER, so a back-dated `_last_success` reproduces a long offline.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import Mock

import aiohttp
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.eveus.const import (
    DOMAIN,
    EVENT_CHARGING_STARTED,
    EVENT_SESSION_ENDED,
)
from custom_components.eveus.coordinator import STALE_STATE_AFTER, ChargerCoordinator

_ENTRY_ID = "e1"
_ISSUE_ID = f"device_error_{_ENTRY_ID}"


class FakeCharger:
    """Minimal charger stub. get_status returns the prepared dict or raises."""

    def __init__(self):
        self._data: dict = {}
        self._exc: BaseException | None = None
        self.capabilities: set = set()
        self.sw_version_loads = 0
        self.sw_version: str | None = None
        # Mirrors ChargerV1: the real one swallows its own error and returns, so
        # a failed read is indistinguishable from a successful one except that
        # sw_version stays None.
        self.sw_version_found = "EnergyStar V5.23"

    def set_data(self, data: dict) -> None:
        self._data = data
        self._exc = None

    def set_exc(self, exc: BaseException) -> None:
        self._exc = exc

    async def get_status(self):
        if self._exc is not None:
            raise self._exc
        return dict(self._data)

    async def async_load_sw_version(self) -> None:
        self.sw_version_loads += 1
        self.sw_version = self.sw_version_found

    def transform_data(self, raw):
        return raw


def _make_coordinator(hass) -> ChargerCoordinator:
    return ChargerCoordinator(hass, FakeCharger(), _ENTRY_ID, "Eveus Test")


async def _poll_ok(coord: ChargerCoordinator, **data):
    coord.charger.set_data(data)
    return await coord._async_update_data()


def _client_response_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(Mock(), (), status=status, message="err")


# --------------------------------------------------------------------------- #
# (a) session lifecycle events
# --------------------------------------------------------------------------- #

async def test_first_refresh_never_fires_event(hass):
    coord = _make_coordinator(hass)
    started = async_capture_events(hass, EVENT_CHARGING_STARTED)
    ended = async_capture_events(hass, EVENT_SESSION_ENDED)

    # First poll ever, already charging: prev_state was None -> no event.
    await _poll_ok(coord, state="charging", sessionEnergy=1.0, sessionTime=10)
    await hass.async_block_till_done()

    assert started == []
    assert ended == []


async def test_charging_started_and_session_ended(hass):
    coord = _make_coordinator(hass)
    started = async_capture_events(hass, EVENT_CHARGING_STARTED)
    ended = async_capture_events(hass, EVENT_SESSION_ENDED)

    await _poll_ok(coord, state="standby")                       # baseline, no event
    await _poll_ok(coord, state="charging", sessionEnergy=2.0, sessionTime=20)   # started
    await _poll_ok(coord, state="charging", sessionEnergy=5.5, sessionTime=99)   # last live values
    await _poll_ok(coord, state="charge_complete")               # ended
    await hass.async_block_till_done()

    assert len(started) == 1
    assert started[0].data["entry_id"] == _ENTRY_ID

    assert len(ended) == 1
    payload = ended[0].data
    assert payload["energy_kwh"] == 5.5      # frozen from the last active poll
    assert payload["duration_s"] == 99
    assert payload["ended_state"] == "charge_complete"
    assert payload["device_name"] == "Eveus Test"

    # last_session published and live counters reset after firing
    assert coord.last_session["energy_kwh"] == 5.5
    assert coord.last_session["duration_s"] == 99
    assert coord._live_energy is None
    assert coord._live_time is None


# --------------------------------------------------------------------------- #
# (b) stale-baseline fix (regression for the session_ended-dropped-on-blip bug)
# --------------------------------------------------------------------------- #

async def test_brief_blip_preserves_baseline(hass):
    """A single failed poll must NOT drop the baseline: session_ended still fires."""
    coord = _make_coordinator(hass)
    ended = async_capture_events(hass, EVENT_SESSION_ENDED)

    await _poll_ok(coord, state="charging", sessionEnergy=7.0, sessionTime=42)

    # one failed poll (short network blip)
    coord.charger.set_exc(aiohttp.ClientConnectionError("blip"))
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()

    # charger recovers shortly after, already back in standby (session ended)
    await _poll_ok(coord, state="standby")
    await hass.async_block_till_done()

    assert len(ended) == 1
    assert ended[0].data["energy_kwh"] == 7.0
    assert ended[0].data["duration_s"] == 42


async def test_long_offline_drops_baseline(hass):
    """A gap longer than STALE_STATE_AFTER must suppress the stale transition."""
    coord = _make_coordinator(hass)
    ended = async_capture_events(hass, EVENT_SESSION_ENDED)

    await _poll_ok(coord, state="charging", sessionEnergy=7.0, sessionTime=42)

    # simulate a long offline: the last good poll was > STALE_STATE_AFTER ago
    coord._last_success = dt_util.utcnow() - (STALE_STATE_AFTER + timedelta(minutes=1))

    await _poll_ok(coord, state="standby")
    await hass.async_block_till_done()

    assert ended == []


# --------------------------------------------------------------------------- #
# (c) error paths
# --------------------------------------------------------------------------- #

async def test_401_is_an_ordinary_error_not_an_auth_failure(hass):
    """No auth branch here: /main is a POST, and POST checks no credentials.

    ConfigEntryAuthFailed would stop polling for good — the core reschedules only
    when the failure was not an auth failure — so an unreachable branch that
    could never be right for this hardware was removed. Credentials are the
    config flow's job (it probes the handler that does check them).
    """
    coord = _make_coordinator(hass)
    coord.charger.set_exc(_client_response_error(401))

    with pytest.raises(UpdateFailed):
        await coord._async_update_data()

    assert ir.async_get(hass).async_get_issue(DOMAIN, _ISSUE_ID) is not None


async def test_unreachable_raises_updatefailed_no_issue(hass):
    coord = _make_coordinator(hass)

    for exc in (aiohttp.ClientConnectionError("down"), TimeoutError()):
        coord.charger.set_exc(exc)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert ir.async_get(hass).async_get_issue(DOMAIN, _ISSUE_ID) is None


async def test_other_error_creates_issue_then_recovery_clears_it(hass):
    coord = _make_coordinator(hass)

    coord.charger.set_exc(RuntimeError("boom"))
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _ISSUE_ID)
    assert issue is not None
    assert issue.translation_placeholders == {"device_name": "Eveus Test"}

    # a subsequent successful poll deletes the issue
    await _poll_ok(coord, state="standby")
    assert ir.async_get(hass).async_get_issue(DOMAIN, _ISSUE_ID) is None


# --------------------------------------------------------------------------- #
# (d) dynamic polling interval
# --------------------------------------------------------------------------- #

async def test_dynamic_interval(hass):
    coord = _make_coordinator(hass)

    await _poll_ok(coord, state="charging")
    assert coord.update_interval == timedelta(seconds=30)

    await _poll_ok(coord, state="standby")
    assert coord.update_interval == timedelta(seconds=60)


# --------------------------------------------------------------------------- #
# (e) systemTime localization: V1 sends a naive wall-clock; the coordinator
#     localizes it to HA's timezone (not the host OS tz).
# --------------------------------------------------------------------------- #

async def test_naive_system_time_localized_to_ha_tz(hass):
    await hass.config.async_set_time_zone("Europe/Kyiv")
    coord = _make_coordinator(hass)

    data = await _poll_ok(coord, state="standby",
                          systemTime=datetime(2026, 7, 1, 1, 25, 50))
    st = data["systemTime"]

    # Now tz-aware in HA's zone, wall-clock components preserved.
    assert st.tzinfo is not None
    assert st.utcoffset() == dt_util.now().utcoffset()   # Europe/Kyiv, not the host
    assert (st.hour, st.minute, st.second) == (1, 25, 50)


async def test_aware_system_time_passes_through(hass):
    """V2 already returns an absolute UTC datetime — leave it untouched."""
    await hass.config.async_set_time_zone("Europe/Kyiv")
    coord = _make_coordinator(hass)

    aware = dt_util.utcnow().replace(microsecond=0)
    data = await _poll_ok(coord, state="standby", systemTime=aware)
    assert data["systemTime"] == aware


async def test_sw_version_is_fetched_once_after_the_first_good_poll(hass):
    """Setup no longer waits for the charger, so this moved into the poll.

    Generations whose /main carries no firmware version read it from the page
    the station serves. Doing that at setup would burn its timeout while the
    station is offline and never retry once the entry had loaded.
    """
    coord = _make_coordinator(hass)
    charger = coord.charger

    charger.set_exc(aiohttp.ClientConnectionError("offline"))
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
    assert charger.sw_version_loads == 0, "nothing to read while the station is down"

    await _poll_ok(coord, state="standby")
    assert charger.sw_version_loads == 1

    await _poll_ok(coord, state="charging")
    assert charger.sw_version_loads == 1, "once per entry, not once per poll"


async def test_sw_version_is_retried_when_the_first_read_finds_nothing(hass):
    """A failed read must not count as done.

    ChargerV1.async_load_sw_version swallows its own error and returns, so
    flagging "loaded" on the mere absence of an exception left sw_version None
    until the next reload — and the read fails exactly when it is most likely
    to: the station has only just come back up.
    """
    coord = _make_coordinator(hass)
    charger = coord.charger
    charger.sw_version_found = None          # the GET failed inside the charger

    await _poll_ok(coord, state="standby")
    assert charger.sw_version_loads == 1
    assert charger.sw_version is None

    charger.sw_version_found = "EnergyStar V5.23"   # station is up now
    await _poll_ok(coord, state="standby")
    assert charger.sw_version == "EnergyStar V5.23"

    await _poll_ok(coord, state="charging")
    assert charger.sw_version_loads == 2, "stops once it actually has a version"


async def test_sw_version_retries_are_bounded(hass):
    """A generation that never reports a version must not be asked forever.

    This is a GET with a 10s timeout sitting inside the poll loop.
    """
    coord = _make_coordinator(hass)
    charger = coord.charger
    charger.sw_version_found = None

    for _ in range(6):
        await _poll_ok(coord, state="standby")

    assert charger.sw_version_loads == 3
