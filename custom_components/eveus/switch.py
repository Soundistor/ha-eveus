"""Переключатель включения/выключения зарядки."""

from __future__ import annotations
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    charger = hass.data[DOMAIN][entry.entry_id]["charger"]

    # Все модели умеют включать/выключать в нашем API
    async_add_entities([ChargerSwitch(coordinator, charger)], True)


class ChargerSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, charger):
        super().__init__(coordinator)
        self._charger = charger
        self._attr_name = f"Charging ({charger.ip})"
        self._attr_unique_id = f"{charger.ip}-charging"

    @property
    def is_on(self) -> bool:
        """Включён ли заряд? Мы смотрим поле `evseEnabled`."""
        # v1/ v2 используют одно поле `evseEnabled`: 0 – включено, 1 – выключено
        enabled = self.coordinator.data.get("evseEnabled")
        if enabled is None:
            return False
        # Если v1: 0 – работает → True, 1 – остановлен → False
        # Если v2: 0 – старт → True, 1 – стоп → False
        return enabled == 0

    async def async_turn_on(self, **kwargs):
        await self._charger.set_enabled(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self._charger.set_enabled(False)
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._charger.ip)},
            "name": f"EV charger {self._charger.ip}",
            "manufacturer": "YourManufacturer",
            "model": self._charger.__class__.__name__,
        }