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

# ground=0 → нет земли, защита активна (SAFETY: on=Unsafe); groundCtrl=1 → PE control
# включён на станции (конфиг-флаг, не авария) — подтверждено на живом устройстве
_ACTIVE_VALUE = {"ground": 0, "groundCtrl": 1}

DEBOUNCE_THRESHOLD = 3

# The faults the ground sensor itself represents. The station declaring one by
# state is positive evidence, and it outranks whatever `ground` reads — including
# the case where the station is not monitoring PE at all.
_GROUND_FAULT_STATES = {"no_ground", "grounding_error"}

BINARY_SENSORS = [
    BinarySensorEntityDescription(key="ground",     name="ground",     translation_key="ground",      device_class=BinarySensorDeviceClass.SAFETY),
    BinarySensorEntityDescription(key="groundCtrl", name="groundctrl", translation_key="ground_ctrl", entity_category=EntityCategory.DIAGNOSTIC),
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
        self._debounced_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Derive the first state from what the coordinator already holds instead
        # of publishing the initial constant. _debounced_on starts as None, which
        # is correct for a SAFETY sensor with no reading yet but wrong for
        # groundCtrl — a stored config flag the station reports as-is.
        self._recompute()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._recompute()
        super()._handle_coordinator_update()

    def _recompute(self) -> None:
        is_safety = self.entity_description.device_class is BinarySensorDeviceClass.SAFETY
        data = self.coordinator.data

        if not (self.coordinator.last_update_success and data):
            # A failed poll is not a reading. On the FIRST failure the core still
            # notifies listeners while coordinator.data holds the PREVIOUS frame
            # (data is assigned only in the success branch), so counting it would
            # walk the debounce to its threshold on a frame already counted — two
            # real "no ground" readings plus one failure used to trip the sensor.
            # Drop the streak; keep the last known state, because offline is this
            # device's normal condition and "off" on a SAFETY class would read as
            # "ground is fine".
            if is_safety:
                self._debounce_count = 0
            return

        key = self.entity_description.key
        raw_on = data.get(key) == _ACTIVE_VALUE[key]

        if not is_safety:
            # Not a safety signal (groundCtrl is a stored config flag): the
            # station reports it as-is, debouncing only delays the reading
            # by three polls.
            self._debounced_on = raw_on
            return

        state = data.get("state", "")
        substate = data.get("subState", "")

        if state in _GROUND_FAULT_STATES or substate in _GROUND_FAULT_STATES:
            # The station declared a grounding fault itself. That is positive
            # evidence and outranks the `ground` field: this branch used to fall
            # through to "raw off -> count 0", so a declared grounding_error with
            # ground=1 made the SAFETY sensor claim "safe" during the very fault
            # it exists to report.
            self._debounce_count = DEBOUNCE_THRESHOLD
            self._debounced_on = True
            return

        if data.get("groundCtrl") != 1:
            # PE monitoring is off, so the station is not checking earth. `ground`
            # reads 1 with monitoring on and off alike (measured live 2026-08-13:
            # groundCtrl 1->0->1, ground never moved), which means "off" here is a
            # confirmation we cannot make — report unknown instead. `!= 1` and not
            # `== 0` on purpose: a missing key must not read as "monitoring on".
            self._debounce_count = 0
            self._debounced_on = None
            return

        if key not in data:
            # Not observed in any frame taken so far; don't invent a reading in
            # either direction.
            return

        if state in FIRMWARE_FAULT_STATES or substate in FIRMWARE_FAULT_STATES:
            # Other firmware faults bypass debounce — trigger immediately
            self._debounce_count = DEBOUNCE_THRESHOLD if raw_on else 0
        elif raw_on:
            self._debounce_count = min(self._debounce_count + 1, DEBOUNCE_THRESHOLD)
        else:
            self._debounce_count = 0
        self._debounced_on = self._debounce_count >= DEBOUNCE_THRESHOLD

    @property
    def is_on(self) -> bool | None:
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
