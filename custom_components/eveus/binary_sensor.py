"""Бинарные датчики – ground, groundCtrl, …"""

from __future__ import annotations
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

BINARY_SENSORS = [
    BinarySensorEntityDescription(key="ground", name="Ground", device_class="safety"),
    BinarySensorEntityDescription(key="groundCtrl", name="Ground control", device_class="safety"),
    # добавить любые другие boolean‑поле, которые есть в API
]

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    charger = hass.data[DOMAIN][entry.entry_id]["charger"]

    entities = []
    for description in BINARY_SENSORS:
        if description.key not in charger.capabilities:
            continue
        entities.append(ChargerBinarySensor(coordinator, charger, description))
    async_add_entities(entities, True)


class ChargerBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, charger, description: BinarySensorEntityDescription):
        super().__init__(coordinator)
        self._charger = charger
        self.entity_description = description
        self._attr_unique_id = f"{charger.ip}-{description.key}"
        self._attr_name = f"{description.name} ({charger.ip})"

    @property
    def is_on(self) -> bool:
        val = self.coordinator.data.get(self.entity_description.key)
        # Приводим к bool (для некоторых API может быть 0/1, True/False, "yes"/"no")
        return bool(val)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._charger.ip)},
            "name": f"EV charger {self._charger.ip}",
            "manufacturer": "YourManufacturer",
            "model": self._charger.__class__.__name__,
        }