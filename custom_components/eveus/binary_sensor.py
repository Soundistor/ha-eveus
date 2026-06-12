"""Бинарные датчики – ground, groundCtrl."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

# ground=1 → защита активна; groundCtrl=2 → активна (не просто truthy!)
_ACTIVE_VALUE = {"ground": 1, "groundCtrl": 2}

BINARY_SENSORS = [
    BinarySensorEntityDescription(key="ground",     name="ground",     device_class=BinarySensorDeviceClass.SAFETY),
    BinarySensorEntityDescription(key="groundCtrl", name="groundctrl", device_class=BinarySensorDeviceClass.SAFETY),
]


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    charger = data["charger"]
    prefix = data.get("prefix", "")

    entities = []
    for description in BINARY_SENSORS:
        if description.key not in charger.capabilities:
            continue
        entities.append(ChargerBinarySensor(coordinator, charger, description, prefix, entry.entry_id))
    async_add_entities(entities, True)


class ChargerBinarySensor(CoordinatorEntity, BinarySensorEntity):

    def __init__(self, coordinator, charger, description: BinarySensorEntityDescription,
                 prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        self.entity_description = description
        uid = f"{prefix}_{description.name}" if prefix else f"{entry_id}_{description.name}"
        self._attr_unique_id = uid
        self._attr_name = f"{prefix} {description.name}" if prefix else description.name

    @property
    def is_on(self) -> bool:
        val = self.coordinator.data.get(self.entity_description.key)
        return val == _ACTIVE_VALUE[self.entity_description.key]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._charger.ip)},
            name=f"Eveus {self._charger.ip}",
            manufacturer="Eveus",
            model=self._charger.model_name,
            configuration_url=f"http://{self._charger.ip}",
        )
