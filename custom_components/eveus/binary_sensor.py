"""Бинарные датчики – ground, groundCtrl."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, friendly_device_name
from .coordinator import FIRMWARE_FAULT_STATES

# ground=1 → защита активна; groundCtrl=2 → активна (не просто truthy!)
_ACTIVE_VALUE = {"ground": 1, "groundCtrl": 2}

DEBOUNCE_THRESHOLD = 3

BINARY_SENSORS = [
    BinarySensorEntityDescription(key="ground",     name="ground",     translation_key="ground",      device_class=BinarySensorDeviceClass.SAFETY),
    BinarySensorEntityDescription(key="groundCtrl", name="groundctrl", translation_key="ground_ctrl", device_class=BinarySensorDeviceClass.SAFETY),
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

    _attr_has_entity_name = True

    def __init__(self, coordinator, charger, description: BinarySensorEntityDescription,
                 prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        self._entry_id = entry_id
        self._device_name = friendly_device_name(prefix, charger.ip)
        self.entity_description = description
        uid = f"{prefix}_{description.name}" if prefix else f"{entry_id}_{description.name}"
        self._attr_unique_id = uid
        self._debounce_count = 0
        self._debounced_on = False

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data:
            val = self.coordinator.data.get(self.entity_description.key)
            raw_on = val == _ACTIVE_VALUE[self.entity_description.key]
            # Firmware faults bypass debounce — trigger immediately
            state = self.coordinator.data.get("state", "")
            substate = self.coordinator.data.get("subState", "")
            is_firmware_fault = state in FIRMWARE_FAULT_STATES or substate in FIRMWARE_FAULT_STATES
            if is_firmware_fault:
                self._debounce_count = DEBOUNCE_THRESHOLD if raw_on else 0
            elif raw_on:
                self._debounce_count = min(self._debounce_count + 1, DEBOUNCE_THRESHOLD)
            else:
                self._debounce_count = 0
            self._debounced_on = self._debounce_count >= DEBOUNCE_THRESHOLD
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool:
        return self._debounced_on

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer="Eveus",
            model=self._charger.model_name,
            configuration_url=f"http://{self._charger.ip}",
        )
