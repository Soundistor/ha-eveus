"""Diagnostics support for Eveus."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import EveusConfigEntry

_TO_REDACT = {"password", "ip_address", "username"}
# STA_IP_Addres — spelled exactly as the firmware sends it (one "s").
_DATA_REDACT = {"serialNum", "serialNumCPU", "stationId", "STA_IP_Addres"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: EveusConfigEntry) -> dict:
    data = entry.runtime_data
    coordinator = data.coordinator
    return {
        "config": async_redact_data(dict(entry.data), _TO_REDACT),
        "coordinator_data": (
            async_redact_data(coordinator.data, _DATA_REDACT)
            if coordinator.data
            else coordinator.data
        ),
        # A failed version read is silent by design (it must not break the poll),
        # so this is the only place its cause is recoverable. The attempt count
        # separates one transient miss from "gave up".
        "sw_version": {
            "value": coordinator.charger.sw_version,
            "error": coordinator.charger.sw_version_error,
            "attempts": coordinator._sw_version_attempts,
            "gave_up": coordinator._sw_version_loaded
            and coordinator.charger.sw_version is None,
        },
    }
