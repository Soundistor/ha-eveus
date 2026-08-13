"""DataUpdateCoordinator – единственная точка получения данных от зарядки."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .charger.base import BaseCharger
from .const import (
    DOMAIN,
    EVENT_CHARGING_STARTED,
    EVENT_SESSION_ENDED,
    SESSION_ACTIVE_STATES,
    session_transition,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EveusData:
    """Runtime data stored on the config entry (entry.runtime_data)."""

    charger: BaseCharger
    coordinator: ChargerCoordinator
    prefix: str


type EveusConfigEntry = ConfigEntry[EveusData]

# Charger is unreachable (powered off / unplugged / off the network). This is a
# normal state for this device — surface it as "unavailable" entities only, not
# as a repair issue the user has to act on.
UNREACHABLE_ERRORS = (aiohttp.ClientConnectionError, asyncio.TimeoutError)

# If more than this elapses between two successful polls, the charger/HA was
# offline long enough that a state remembered from before the gap is no longer a
# valid baseline — replaying its transition would fire a stale session_ended
# with pre-offline figures. Reset the baseline instead. A short blip (one or two
# missed polls, well under this) is preserved, so a session that ends across a
# brief network hiccup is still reported.
STALE_STATE_AFTER = timedelta(minutes=15)

# /main serves cached values, and a write needs a couple of poll cycles before
# it shows up there: the station's own web client discards exactly the next 2
# responses after every write (3 after a current change), globally rather than
# per field. Refreshing the instant a write returns therefore reads the OLD
# value back and undoes what the user just did on screen. Wait this long first.
WRITE_SETTLE = timedelta(seconds=3)

# How many polls may try to fetch the firmware version before giving up until
# the next reload. V2 reports it in /main and never gets here; V1 needs a GET
# that can fail exactly when the station has only just come back up.
_SW_VERSION_MAX_ATTEMPTS = 3

# Firmware-level faults that bypass safety debounce in binary sensors. Every
# member must be a value some state map actually produces — see
# test_fault_states_all_come_from_a_state_map. cpu_error and relay_stuck used to
# sit here and no map ever emitted them.
FIRMWARE_FAULT_STATES = frozenset({
    "no_ground",                          # V1 main state
    "relay_error", "software_failure",    # V2 subState
    "pilot_error", "gfci_test_failure",   # V2 subState
    "grounding_error",                    # V2 subState — the fault the ground
                                          # binary sensor represents, so it must
                                          # not be the slowest one to confirm
})


class ChargerCoordinator(DataUpdateCoordinator[dict[str, Any]]):

    def __init__(
        self,
        hass: HomeAssistant,
        charger,
        entry_id,
        device_name,
        update_interval: int = 30,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=device_name,
            update_interval=timedelta(seconds=update_interval),
        )
        self.charger = charger
        self._entry_id = entry_id
        self._device_name = device_name
        self._prev_state = None
        self._last_success = None
        self._sw_version_loaded = False
        self._sw_version_attempts = 0
        self._live_energy = None
        self._live_time = None
        self.last_session = None

    @callback
    def schedule_refresh_after_write(self) -> None:
        """Refresh once the station has had time to apply a write.

        Deliberately not an immediate `async_request_refresh()` — see
        WRITE_SETTLE. Scheduled rather than awaited so the user's action
        returns at once instead of blocking on the settle time.
        """
        async_call_later(self.hass, WRITE_SETTLE.total_seconds(), self._refresh_now)

    async def _refresh_now(self, _now) -> None:
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            raw = await self.charger.get_status()
            data = self.charger.transform_data(raw)
            # V1 reports systemTime as a naive wall-clock time-of-day; localize it
            # to an absolute instant using HA's configured timezone (not the host
            # OS tz). V2 resolves its own offset in transform_data and hands us an
            # absolute UTC datetime — leave anything tz-aware untouched.
            st = data.get("systemTime")
            if isinstance(st, datetime) and st.tzinfo is None:
                data["systemTime"] = dt_util.now().replace(
                    hour=st.hour, minute=st.minute, second=st.second, microsecond=0
                )
            ir.async_delete_issue(self.hass, DOMAIN, f"device_error_{self._entry_id}")
            # Dynamic polling: 30s while charging, 60s otherwise
            self.update_interval = timedelta(
                seconds=30 if data.get("state") == "charging" else 60
            )
            now = dt_util.utcnow()
            if (
                self._last_success is not None
                and now - self._last_success > STALE_STATE_AFTER
            ):
                # Long gap since the last good poll: the charger was offline
                # long enough that the remembered state is stale. Drop the
                # baseline so this poll starts fresh and we don't replay a
                # transition that happened while offline.
                self._prev_state = None
            self._last_success = now
            await self._load_sw_version_once()
            self._process_session_events(data)
            return data
        except UNREACHABLE_ERRORS as exc:
            # Expected when the charger is unplugged/powered off — entities go
            # unavailable; don't raise a repair issue. A brief blip keeps the
            # baseline (see STALE_STATE_AFTER); only a long gap resets it.
            raise UpdateFailed(f"Charger unreachable: {exc}") from exc
        except Exception as exc:
            # Charger answered but the request failed (an HTTP error status,
            # malformed response, wrong firmware model, …) — this needs the
            # user's attention.
            #
            # No 401 branch on purpose: /main is a POST, and POST handlers on this
            # firmware check no credentials at all (KB-01 §1.2, live on V1
            # 2026-07-30 and V2 R3.05.4 2026-08-13). A ConfigEntryAuthFailed here
            # would have been unreachable code that, if it ever did fire, stops
            # polling for good — the core only reschedules when the failure was
            # not an auth failure. Credentials are validated in the config flow,
            # which probes the one handler that does check them.
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"device_error_{self._entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="device_error",
                translation_placeholders={"device_name": self._device_name},
            )
            raise UpdateFailed(f"Error updating: {exc}") from exc

    async def _load_sw_version_once(self) -> None:
        """Fetch the firmware version on the first successful poll.

        Generations whose /main carries no version read it from the page the
        station serves (V1); a no-op elsewhere, and never fatal. This runs here
        rather than at setup because setup no longer waits for the charger to be
        reachable — at setup the request would only burn its timeout while the
        station is offline, and would never be retried once the entry loaded.
        """
        if self._sw_version_loaded:
            return
        await self.charger.async_load_sw_version()
        # The flag turns on the RESULT, not on "no exception was raised":
        # ChargerV1.async_load_sw_version swallows its own error and returns, so
        # a failed first attempt looks identical to a successful one from here.
        # Retry on later polls instead, bounded — this is a GET with a 10s
        # timeout inside the poll loop, and a generation that reports no version
        # at all must not be asked forever.
        if self.charger.sw_version is not None:
            self._sw_version_loaded = True
            return
        self._sw_version_attempts += 1
        if self._sw_version_attempts >= _SW_VERSION_MAX_ATTEMPTS:
            self._sw_version_loaded = True

    def _process_session_events(self, data) -> None:
        new_state = data.get("state")

        if new_state in SESSION_ACTIVE_STATES:
            # The firmware wipes sessionEnergy/sessionTime the moment the next
            # session starts, so capture the last values seen while active —
            # they are the only reliable final figures for the ended session.
            se = data.get("sessionEnergy")
            st = data.get("sessionTime")
            if se is not None:
                self._live_energy = se
            if st is not None:
                self._live_time = st

        if self._prev_state is not None:
            event = session_transition(self._prev_state, new_state)
            base = {"entry_id": self._entry_id, "device_name": self._device_name}
            if event == "charging_started":
                self.hass.bus.async_fire(EVENT_CHARGING_STARTED, base)
            elif event == "session_ended":
                self.last_session = {
                    "energy_kwh": self._live_energy,
                    "duration_s": self._live_time,
                    "ended_state": new_state,
                    "ended_at": dt_util.utcnow().isoformat(),
                }
                self.hass.bus.async_fire(EVENT_SESSION_ENDED, {**base, **self.last_session})
                self._live_energy = None
                self._live_time = None

        self._prev_state = new_state
