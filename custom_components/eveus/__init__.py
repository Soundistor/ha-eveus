"""Главный файл интеграции."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, MODEL_V1, MODEL_V2
from .coordinator import ChargerCoordinator
from .charger.v1 import ChargerV1
from .charger.v2 import ChargerV2

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    "sensor",
    "binary_sensor",
    "switch",
    "number",
    "select",
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Инициализация после создания Config Entry."""
    ip = entry.data["ip_address"]
    model = entry.data["model"]
    username = entry.data.get("username")
    password = entry.data.get("password")

    # Выбираем реализацию API
    if model == MODEL_V1:
        charger = ChargerV1(ip, username, password)
    else:
        charger = ChargerV2(ip, username, password)

    # Координатор (по‑умолчанию 30 сек, будет доступен в options)
    coordinator = ChargerCoordinator(
        hass,
        charger,
        update_interval=entry.options.get("update_interval", 30),
    )
    # Первичный опрос – если не удался – конфиг не будет создан
    await coordinator.async_config_entry_first_refresh()

    # Сохраняем в hass.data, чтобы платформы могли достать
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "charger": charger,
        "coordinator": coordinator,
    }

    # Forward к платформам
    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    hass.services.async_register(DOMAIN, "set_current", async_set_current)
    hass.services.async_register(DOMAIN, "set_ai_mode", async_set_ai_mode)

    # Перезапуск при изменении options
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выключаем интеграцию."""
    unload_ok = all(
        await hass.config_entries.async_forward_entry_unload(entry, p)
        for p in PLATFORMS
    )
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["charger"].close()
    return unload_ok


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Обновляем интервал опроса, если пользователь изменил options."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ChargerCoordinator = data["coordinator"]
    coordinator.update_interval = timedelta(
        seconds=entry.options.get("update_interval", 30)
    )
    await coordinator.async_request_refresh()


async def async_set_current(call):
    entity_id = call.data["entity_id"]
    current = call.data["current"]
    # Находим соответствующий number‑entity (можно использовать helper)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": current}
    )

async def async_set_ai_mode(call):
    entity_id = call.data["entity_id"]
    mode = call.data["mode"]
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": mode}
    )