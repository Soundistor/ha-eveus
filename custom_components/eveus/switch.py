"""Switch – включение/выключение зарядки."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    prefix = data.get("prefix", "")
    async_add_entities([ChargerSwitch(data["coordinator"], data["charger"], prefix, entry.entry_id)], True)


class ChargerSwitch(CoordinatorEntity, SwitchEntity):

    _attr_has_entity_name = True
    _attr_translation_key = "charging"

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        uid = f"{prefix}_charging" if prefix else f"{entry_id}_charging"
        self._attr_unique_id = uid
        # Optimistic state shown until the next coordinator poll confirms it
        self._optimistic: bool | None = None

    @property
    def is_on(self) -> bool:
        if self._optimistic is not None:
            return self._optimistic
        enabled = self.coordinator.data.get("evseEnabled")
        if enabled is None:
            return False
        return self._charger.is_charging_active(enabled)

    async def async_turn_on(self, **kwargs):
        await self._charger.set_enabled(True)
        self._optimistic = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self._charger.set_enabled(False)
        self._optimistic = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._charger.ip)},
            name=f"Eveus {self._charger.ip}",
            manufacturer="Eveus",
            model=self._charger.model_name,
            configuration_url=f"http://{self._charger.ip}",
        )
