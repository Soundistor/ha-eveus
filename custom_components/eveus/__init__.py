"""Главный файл интеграции."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, MODEL_V1, CONF_DEVICE_PREFIX
from .coordinator import ChargerCoordinator
from .charger.v1 import ChargerV1
from .charger.v2 import ChargerV2

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "switch", "number", "select", "button"]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version > 1:
        _LOGGER.error("Migration from config entry version %s is not supported", entry.version)
        return False
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ip = entry.data["ip_address"]
    model = entry.data["model"]
    username = entry.data.get("username")
    password = entry.data.get("password")
    prefix = entry.data.get(CONF_DEVICE_PREFIX, "")

    charger = ChargerV1(ip, username, password) if model == MODEL_V1 else ChargerV2(ip, username, password)

    coordinator = ChargerCoordinator(hass, charger)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "charger": charger,
        "coordinator": coordinator,
        "prefix": prefix,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def async_set_current(call):
        entity_id = call.data["entity_id"]
        current = call.data["current"]
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": current}
        )

    async def async_set_ai_mode(call):
        entity_id = call.data["entity_id"]
        mode = call.data["mode"]
        await hass.services.async_call(
            "select", "select_option", {"entity_id": entity_id, "option": mode}
        )

    hass.services.async_register(DOMAIN, "set_current", async_set_current)
    hass.services.async_register(DOMAIN, "set_ai_mode", async_set_ai_mode)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["charger"].close()
    return unload_ok


