"""Главный файл интеграции."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .charger.v1 import ChargerV1
from .charger.v2 import ChargerV2
from .const import CONF_DEVICE_PREFIX, DOMAIN, MODEL_V1, friendly_device_name
from .coordinator import ChargerCoordinator, EveusConfigEntry, EveusData

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "switch", "number", "select", "button"]

# Repair issues raised by older versions under ids nothing deletes any more, so
# they sit in .storage forever: `cannot_connect` was still live on prod
# 2026-08-13, created 2026-06-14, and `device_error` was the shared id before it
# gained a per-entry suffix. Deleting an issue that isn't there is a no-op.
LEGACY_ISSUE_IDS = ("cannot_connect", "device_error")


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version > 1:
        _LOGGER.error("Migration from config entry version %s is not supported", entry.version)
        return False
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EveusConfigEntry) -> bool:
    ip = entry.data["ip_address"]
    model = entry.data["model"]
    username = entry.data.get("username")
    password = entry.data.get("password")
    prefix = entry.data.get(CONF_DEVICE_PREFIX, "")

    for legacy in LEGACY_ISSUE_IDS:
        ir.async_delete_issue(hass, DOMAIN, legacy)

    charger = (
        ChargerV1(ip, username, password, hass=hass)
        if model == MODEL_V1
        else ChargerV2(ip, username, password, hass=hass)
    )
    device_name = friendly_device_name(prefix, ip)

    coordinator = ChargerCoordinator(hass, charger, entry.entry_id, device_name)
    # Deliberately NOT async_config_entry_first_refresh(): an unreachable charger
    # must not block setup. This device is offline most of the time (it comes up
    # for a charging session), so gating the entry on the first poll meant almost
    # every HA restart left it in SETUP_RETRY — no entities at all — and recovery
    # was up to 10 minutes away (the core's retry backoff doubles to a 600 s
    # ceiling; measured on prod 2026-08-13). Loading regardless costs nothing: the
    # entity set comes from charger.capabilities, not from poll data, so entities
    # register as unavailable and the normal 60 s poll picks the station up.
    # Awaited on purpose — a fire-and-forget refresh would let entities register
    # while last_update_success is still True and data is None.
    await coordinator.async_refresh()

    entry.runtime_data = EveusData(charger=charger, coordinator=coordinator, prefix=prefix)

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

    if not hass.services.has_service(DOMAIN, "set_current"):
        hass.services.async_register(DOMAIN, "set_current", async_set_current)
        hass.services.async_register(DOMAIN, "set_ai_mode", async_set_ai_mode)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EveusConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # The charger uses HA's shared aiohttp session — nothing to close;
        # entry.runtime_data is cleared by HA automatically.
        remaining = [
            e
            for e in hass.config_entries.async_loaded_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining:
            hass.services.async_remove(DOMAIN, "set_current")
            hass.services.async_remove(DOMAIN, "set_ai_mode")
    return unload_ok


