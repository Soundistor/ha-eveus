"""Сенсоры зарядки."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

# name = lowercase key — определяет entity_id как {platform}.{prefix}_{name}
SENSOR_DESCRIPTIONS: list[SensorEntityDescription] = [
    SensorEntityDescription(key="state",         name="state",         icon="mdi:power"),
    SensorEntityDescription(key="currentSet",    name="currentset",    native_unit_of_measurement="A",   device_class=SensorDeviceClass.CURRENT),
    SensorEntityDescription(key="curDesign",     name="curdesign",     native_unit_of_measurement="A",   device_class=SensorDeviceClass.CURRENT),
    SensorEntityDescription(key="voltMeas1",     name="voltmeas1",     native_unit_of_measurement="V",   device_class=SensorDeviceClass.VOLTAGE),
    SensorEntityDescription(key="curMeas1",      name="curmeas1",      native_unit_of_measurement="A",   device_class=SensorDeviceClass.CURRENT),
    SensorEntityDescription(key="powerMeas",     name="powermeas",     native_unit_of_measurement="W",   device_class=SensorDeviceClass.POWER),
    SensorEntityDescription(key="temperature1",  name="temperature1",  native_unit_of_measurement="°C",  device_class=SensorDeviceClass.TEMPERATURE),
    SensorEntityDescription(key="temperature2",  name="temperature2",  native_unit_of_measurement="°C",  device_class=SensorDeviceClass.TEMPERATURE),
    SensorEntityDescription(key="aiStatus",      name="aistatus",      icon="mdi:brain"),
    SensorEntityDescription(key="aiVoltage",     name="aivoltage",     native_unit_of_measurement="V",   device_class=SensorDeviceClass.VOLTAGE),
    SensorEntityDescription(key="sessionTime",   name="sessiontime",   native_unit_of_measurement="s",   device_class=SensorDeviceClass.DURATION),
    SensorEntityDescription(key="sessionEnergy", name="sessionenergy", native_unit_of_measurement="kWh", device_class=SensorDeviceClass.ENERGY),
    SensorEntityDescription(
        key="totalEnergy", name="totalenergy",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(key="systemTime",    name="systemtime",    icon="mdi:clock"),
    SensorEntityDescription(
        key="leakValue", name="leakvalue",
        native_unit_of_measurement="mA",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(key="newsessiontime", name="newsessiontime", icon="mdi:battery-clock-outline"),
    SensorEntityDescription(key="subState",      name="substate",      icon="mdi:information"),
    SensorEntityDescription(
        key="vBat", name="vbat",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="RSSI", name="rssi",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="IEM1", name="iem1",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="IEM2", name="iem2",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
]


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
    async_add_entities(entities, True)


class ChargerSensor(CoordinatorEntity, SensorEntity):

    def __init__(self, coordinator, charger, description: SensorEntityDescription,
                 prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        self._entry_id = entry_id
        self.entity_description = description
        uid = f"{prefix}_{description.name}" if prefix else f"{entry_id}_{description.name}"
        self._attr_unique_id = uid
        self._attr_name = f"{prefix} {description.name}" if prefix else description.name

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
