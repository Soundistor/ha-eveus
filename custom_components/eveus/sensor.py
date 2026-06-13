"""Сенсоры зарядки."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_V1_STATE_OPTIONS = [
    "no_data", "ready", "waiting", "charging", "current_leak", "cpu_error",
    "no_ground", "overheat_plug", "overheat_relay", "overcurrent", "overvoltage",
    "undervoltage", "limited_by_time", "limited_by_energy", "limited_by_money",
    "limited_by_schedule1", "limited_by_schedule2", "disabled_by_user",
    "relay_stuck", "limited_by_ai_mode",
]
_V2_STATE_OPTIONS = [
    "startup", "system_test", "standby", "connected", "charging",
    "charge_complete", "paused", "error",
]
_STATE_OPTIONS = list(dict.fromkeys(_V1_STATE_OPTIONS + _V2_STATE_OPTIONS)) + ["unknown"]

_SUBSTATE_OPTIONS = [
    "no_error", "grounding_error", "current_leak_high", "relay_error",
    "current_leak_low", "box_overheat", "plug_overheat", "pilot_error",
    "low_voltage", "diode_error", "overcurrent", "interface_timeout",
    "software_failure", "gfci_test_failure", "high_voltage",
    "no_limits", "limited_by_user", "energy_limit", "time_limit", "cost_limit",
    "schedule1_limit", "schedule1_energy_limit", "schedule2_limit",
    "schedule2_energy_limit", "waiting_for_activation", "paused_by_adaptive_mode",
    "unknown",
]

_AI_STATUS_OPTIONS = ["off", "voltage", "tesla_auto", "power", "unknown"]

# name = lowercase key — определяет entity_id как {platform}.{prefix}_{name}
SENSOR_DESCRIPTIONS: list[SensorEntityDescription] = [
    SensorEntityDescription(
        key="state", name="state", translation_key="state", icon="mdi:power",
        device_class=SensorDeviceClass.ENUM, options=_STATE_OPTIONS,
    ),
    SensorEntityDescription(
        key="currentSet", name="currentset", translation_key="current_set",
        native_unit_of_measurement="A", device_class=SensorDeviceClass.CURRENT,
    ),
    SensorEntityDescription(
        key="curDesign", name="curdesign", translation_key="cur_design",
        native_unit_of_measurement="A", device_class=SensorDeviceClass.CURRENT,
    ),
    SensorEntityDescription(
        key="voltMeas1", name="voltmeas1", translation_key="volt_meas",
        native_unit_of_measurement="V", device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="curMeas1", name="curmeas1", translation_key="cur_meas",
        native_unit_of_measurement="A", device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="powerMeas", name="powermeas", translation_key="power_meas",
        native_unit_of_measurement="W", device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature1", name="temperature1", translation_key="temperature1",
        native_unit_of_measurement="°C", device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature2", name="temperature2", translation_key="temperature2",
        native_unit_of_measurement="°C", device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="aiStatus", name="aistatus", translation_key="ai_status", icon="mdi:brain",
        device_class=SensorDeviceClass.ENUM, options=_AI_STATUS_OPTIONS,
    ),
    SensorEntityDescription(
        key="aiVoltage", name="aivoltage", translation_key="ai_voltage",
        native_unit_of_measurement="V", device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="sessionTime", name="sessiontime", translation_key="session_time",
        native_unit_of_measurement="s", device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # sessionEnergy handled by SessionEnergySensor below (needs last_reset tracking)
    SensorEntityDescription(
        key="totalEnergy", name="totalenergy", translation_key="total_energy",
        native_unit_of_measurement="kWh", device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="systemTime", name="systemtime", translation_key="system_time",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="leakValue", name="leakvalue", translation_key="leak_value",
        native_unit_of_measurement="mA", state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="subState", name="substate", translation_key="sub_state",
        icon="mdi:information",
        device_class=SensorDeviceClass.ENUM, options=_SUBSTATE_OPTIONS,
    ),
    SensorEntityDescription(
        key="vBat", name="vbat", translation_key="v_bat",
        native_unit_of_measurement="V", device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="RSSI", name="rssi", translation_key="rssi",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="IEM1", name="iem1", translation_key="iem1",
        native_unit_of_measurement="kWh", device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="IEM2", name="iem2", translation_key="iem2",
        native_unit_of_measurement="kWh", device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
]


_SESSION_ENERGY_DESCRIPTION = SensorEntityDescription(
    key="sessionEnergy",
    name="sessionenergy",
    translation_key="session_energy",
    native_unit_of_measurement="kWh",
    device_class=SensorDeviceClass.ENERGY,
    state_class=SensorStateClass.TOTAL,
)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    charger = data["charger"]
    prefix = data.get("prefix", "")

    entities = []
    for description in SENSOR_DESCRIPTIONS:
        if description.key not in charger.capabilities:
            continue
        entities.append(ChargerSensor(coordinator, charger, description, prefix, entry.entry_id))
    if "sessionEnergy" in charger.capabilities:
        entities.append(SessionEnergySensor(coordinator, charger, _SESSION_ENERGY_DESCRIPTION, prefix, entry.entry_id))
    async_add_entities(entities, True)


class ChargerSensor(CoordinatorEntity, SensorEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator, charger, description: SensorEntityDescription,
                 prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        self._entry_id = entry_id
        self.entity_description = description
        uid = f"{prefix}_{description.name}" if prefix else f"{entry_id}_{description.name}"
        self._attr_unique_id = uid

    @property
    def native_value(self):
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._charger.ip)},
            name=f"Eveus {self._charger.ip}",
            manufacturer="Eveus",
            model=self._charger.model_name,
            sw_version=self.coordinator.data.get("verFWMain") if self.coordinator.data else None,
            configuration_url=f"http://{self._charger.ip}",
        )


class SessionEnergySensor(ChargerSensor):
    """Session energy sensor with last_reset support for correct HA statistics."""

    def __init__(self, coordinator, charger, description, prefix, entry_id):
        super().__init__(coordinator, charger, description, prefix, entry_id)
        self._attr_last_reset = None
        self._prev_energy: float | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        current = self.coordinator.data.get("sessionEnergy") if self.coordinator.data else None
        if self._prev_energy is not None and current is not None and current < self._prev_energy:
            self._attr_last_reset = dt_util.utcnow()
        self._prev_energy = current
        super()._handle_coordinator_update()
