"""Diagnostics support for Eveus."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import EveusConfigEntry

_TO_REDACT = {"password", "ip_address", "username"}
_DATA_REDACT = {"serialNum", "serialNumCPU"}


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
    }
