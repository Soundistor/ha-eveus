"""Сенсоры с атрибутами зарядки."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

# Список датчиков, которые мы хотим показывать в UI.
# По‑молчанию выводим «state» как основной атрибут, остальные – как атрибуты.
SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(key="state", name="State", icon="mdi:power"),
    SensorEntityDescription(key="currentSet", name="Set current", native_unit_of_measurement="A", device_class="current"),
    SensorEntityDescription(key="voltMeas1", name="Voltage", native_unit_of_measurement="V", device_class="voltage"),
    SensorEntityDescription(key="curMeas1", name="Current", native_unit_of_measurement="A", device_class="current"),
    SensorEntityDescription(key="powerMeas", name="Power", native_unit_of_measurement="kW", device_class="power"),
    SensorEntityDescription(key="temperature1", name="Temperature", native_unit_of_measurement="°C", device_class="temperature"),
    SensorEntityDescription(key="sessionEnergy", name="Session energy", native_unit_of_measurement="kWh", device_class="energy"),
    SensorEntityDescription(key="sessionTime", name="Session time", native_unit_of_measurement="s", device_class="duration"),
    SensorEntityDescription(key="totalEnergy", name="Total energy", native_unit_of_measurement="kWh", device_class="energy"),
    # Добавляйте любые другие атрибуты из `json_attributes`, которые вам нужны в UI
]

async def async_setup_entry(hass, entry, async_add_entities):
    """Настраиваем сенсоры."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    charger = hass.data[DOMAIN][entry.entry_id]["charger"]

    entities = []
    for description in SENSOR_DESCRIPTIONS:
        # Если у конкретной модели нет такого атрибута – не создаём.
        if description.key not in charger.capabilities:
            continue
        entities.append(
            ChargerSensor(coordinator, charger, description)
        )
    async_add_entities(entities, True)


class ChargerSensor(CoordinatorEntity, SensorEntity):
    """Один сенсор, данные берутся из `coordinator.data`."""

    def __init__(self, coordinator, charger, description: SensorEntityDescription):
        super().__init__(coordinator)
        self._charger = charger
        self.entity_description = description
        self._attr_unique_id = f"{charger.ip}-{description.key}"
        self._attr_name = f"{description.name} ({charger.ip})"

    @property
    def native_value(self):
        """Текущее значение."""
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self):
        """Выдаём всё, что пришло в статус, кроме «основного» значения."""
        # Атрибуты, которые пользователь возможно не захочет видеть в списке сенсоров,
        # но они полезны в атрибутах.
        return {
            k: v
            for k, v in self.coordinator.data.items()
            if k != self.entity_description.key
        }

    @property
    def device_info(self):
        """Привязываем все сущности к одному устройству."""
        return {
            "identifiers": {(DOMAIN, self._charger.ip)},
            "name": f"EV charger {self._charger.ip}",
            "manufacturer": "YourManufacturer",
            "model": self._charger.__class__.__name__,
        }