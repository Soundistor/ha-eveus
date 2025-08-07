"""NumberEntity – текущий установленный ток."""

from __future__ import annotations
from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

NUMBER_DESCRIPTIONS = [
    NumberEntityDescription(
        key="current_set",
        name="Current Regulator",
        native_min_value=7,
        native_max_value=32,
        native_step=1,
        unit_of_measurement="A",
        icon="mdi:current-ac",
    )
]

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    charger = hass.data[DOMAIN][entry.entry_id]["charger"]

    entities = [
        ChargerCurrentNumber(coordinator, charger, NUMBER_DESCRIPTIONS[0])
    ]
    async_add_entities(entities, True)


class ChargerCurrentNumber(CoordinatorEntity, NumberEntity):
    def __init__(self, coordinator, charger, description: NumberEntityDescription):
        super().__init__(coordinator)
        self._charger = charger
        self.entity_description = description
        self._attr_unique_id = f"{charger.ip}-{description.key}"
        self._attr_name = f"{description.name} ({charger.ip})"

    @property
    def native_value(self):
        """Текущее значение тока, которое передаёт зарядка."""
        # В API поле называется currentSet (обычно 0‑32)
        return self.coordinator.data.get("currentSet")

    async def async_set_value(self, value: float) -> None:
        """Установить ток."""
        await self._charger.set_current(int(value))
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._charger.ip)},
            "name": f"EV charger {self._charger.ip}",
            "manufacturer": "YourManufacturer",
            "model": self._charger.__class__.__name__,
        }