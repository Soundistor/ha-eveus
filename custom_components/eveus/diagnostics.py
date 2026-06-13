"""Diagnostics support for Eveus."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_TO_REDACT = {"password", "ip_address", "username"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    return {
        "config": async_redact_data(dict(entry.data), _TO_REDACT),
        "coordinator_data": coordinator.data,
    }
