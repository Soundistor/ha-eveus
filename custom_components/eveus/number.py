"""NumberEntity – регулятор тока зарядки."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, friendly_device_name

NUMBER_DESCRIPTION = NumberEntityDescription(
    key="currentSet",
    name="current_set",
    translation_key="current_set",
    native_max_value=32,
    native_step=1,
    native_unit_of_measurement="A",
    icon="mdi:current-ac",
)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    prefix = data.get("prefix", "")
    async_add_entities(
        [ChargerCurrentNumber(data["coordinator"], data["charger"], prefix, entry.entry_id)],
        True,
    )


class ChargerCurrentNumber(CoordinatorEntity, NumberEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        self._entry_id = entry_id
        self._device_name = friendly_device_name(prefix, charger.ip)
        self.entity_description = NUMBER_DESCRIPTION
        uid = f"{prefix}_current_set" if prefix else f"{entry_id}_current_set"
        self._attr_unique_id = uid

    @property
    def native_min_value(self) -> float:
        return self._charger.min_current

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("currentSet")

    async def async_set_value(self, value: float) -> None:
        await self._charger.set_current(int(value))
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer="Eveus",
            model=self._charger.model_name,
            configuration_url=f"http://{self._charger.ip}",
        )
