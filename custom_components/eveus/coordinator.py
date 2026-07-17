"""DataUpdateCoordinator – единственная точка получения данных от зарядки."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
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

# Firmware-level faults that bypass safety debounce in binary sensors
FIRMWARE_FAULT_STATES = frozenset({
    "cpu_error", "relay_stuck",          # V1 main state
    "relay_error", "software_failure",   # V2 subState
    "pilot_error", "gfci_test_failure",  # V2 subState
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
        self._live_energy = None
        self._live_time = None
        self.last_session = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            raw = await self.charger.get_status()
            data = self.charger.transform_data(raw)
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
            self._process_session_events(data)
            return data
        except UNREACHABLE_ERRORS as exc:
            # Expected when the charger is unplugged/powered off — entities go
            # unavailable; don't raise a repair issue. A brief blip keeps the
            # baseline (see STALE_STATE_AFTER); only a long gap resets it.
            raise UpdateFailed(f"Charger unreachable: {exc}") from exc
        except aiohttp.ClientResponseError as exc:
            if exc.status == 401:
                # Invalid credentials — HA starts the re-auth flow.
                raise ConfigEntryAuthFailed(f"Invalid credentials: {exc}") from exc
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
        except Exception as exc:
            # Charger answered but the request failed (auth, malformed response,
            # wrong firmware model, …) — this needs the user's attention.
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
