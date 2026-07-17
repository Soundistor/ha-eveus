"""Бинарные датчики – ground, groundCtrl."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import FIRMWARE_FAULT_STATES, EveusConfigEntry
from .entity import EveusEntity

PARALLEL_UPDATES = 0

# ground=1 → защита активна; groundCtrl=2 → активна (не просто truthy!)
_ACTIVE_VALUE = {"ground": 1, "groundCtrl": 2}

DEBOUNCE_THRESHOLD = 3

BINARY_SENSORS = [
    BinarySensorEntityDescription(key="ground",     name="ground",     translation_key="ground",      device_class=BinarySensorDeviceClass.SAFETY),
    BinarySensorEntityDescription(key="groundCtrl", name="groundctrl", translation_key="ground_ctrl", device_class=BinarySensorDeviceClass.SAFETY),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    coordinator = data.coordinator
    charger = data.charger
    prefix = data.prefix

    entities = []
    for description in BINARY_SENSORS:
        if description.key not in charger.capabilities:
            continue
        entities.append(ChargerBinarySensor(coordinator, charger, description, prefix, entry.entry_id))
    entities.append(EveusConnectivitySensor(coordinator, charger, prefix, entry.entry_id))
    async_add_entities(entities, True)


class ChargerBinarySensor(EveusEntity, BinarySensorEntity):

    def __init__(self, coordinator, charger, description: BinarySensorEntityDescription,
                 prefix: str, entry_id: str):
        super().__init__(coordinator, charger, prefix, entry_id, description.name)
        self.entity_description = description
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


class EveusConnectivitySensor(EveusEntity, BinarySensorEntity):
    """Online/offline status via coordinator.last_update_success.

    Stays available even when the charger is offline — otherwise the sensor
    would go unavailable exactly when it needs to report "disconnected".
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connectivity"

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator, charger, prefix, entry_id, "connectivity")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success
