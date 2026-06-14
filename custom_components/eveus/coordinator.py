"""DataUpdateCoordinator – единственная точка получения данных от зарядки."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Charger is unreachable (powered off / unplugged / off the network). This is a
# normal state for this device — surface it as "unavailable" entities only, not
# as a repair issue the user has to act on.
UNREACHABLE_ERRORS = (aiohttp.ClientConnectionError, asyncio.TimeoutError)

# Firmware-level faults that bypass safety debounce in binary sensors
FIRMWARE_FAULT_STATES = frozenset({
    "cpu_error", "relay_stuck",          # V1 main state
    "relay_error", "software_failure",   # V2 subState
    "pilot_error", "gfci_test_failure",  # V2 subState
})


class ChargerCoordinator(DataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, charger, update_interval: int = 30) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="EV charger",
            update_interval=timedelta(seconds=update_interval),
        )
        self.charger = charger

    async def _async_update_data(self):
        try:
            raw = await self.charger.get_status()
            data = self.charger.transform_data(raw)
            ir.async_delete_issue(self.hass, DOMAIN, "device_error")
            # Dynamic polling: 30s while charging, 60s otherwise
            self.update_interval = timedelta(
                seconds=30 if data.get("state") == "Charging" else 60
            )
            return data
        except UNREACHABLE_ERRORS as exc:
            # Expected when the charger is unplugged/powered off — entities go
            # unavailable; don't raise a repair issue.
            raise UpdateFailed(f"Charger unreachable: {exc}") from exc
        except Exception as exc:
            # Charger answered but the request failed (auth, malformed response,
            # wrong firmware model, …) — this needs the user's attention.
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "device_error",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="device_error",
            )
            raise UpdateFailed(f"Error updating: {exc}") from exc
