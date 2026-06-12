"""Switch – включение/выключение зарядки."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    prefix = data.get("prefix", "")
    async_add_entities([ChargerSwitch(data["coordinator"], data["charger"], prefix, entry.entry_id)], True)


class ChargerSwitch(CoordinatorEntity, SwitchEntity):

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        uid = f"{prefix}_charging" if prefix else f"{entry_id}_charging"
        self._attr_unique_id = uid
        self._attr_name = f"{prefix} charging" if prefix else "charging"

    @property
    def is_on(self) -> bool:
        enabled = self.coordinator.data.get("evseEnabled")
        if enabled is None:
            return False
        return self._charger.is_charging_active(enabled)

    async def async_turn_on(self, **kwargs):
        await self._charger.set_enabled(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self._charger.set_enabled(False)
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._charger.ip)},
            name=f"Eveus {self._charger.ip}",
            manufacturer="Eveus",
            model=self._charger.model_name,
            configuration_url=f"http://{self._charger.ip}",
        )
