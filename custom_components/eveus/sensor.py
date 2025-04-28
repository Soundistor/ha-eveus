from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVoltage,
    PERCENTAGE,
)
from .const import (
    DOMAIN,
    STATE_MAPPING,
    SUBSTATE_ERROR_MAPPING,
    SUBSTATE_NORMAL_MAPPING,
    AI_STATUS_MAPPING,
    # Все остальные атрибуты...
)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up all Eveus sensors."""
    sensors = [
        EveusSensor(entry, "evse_enabled", "EVSE Enabled", None, None),
        EveusSensor(entry, "state", "State", None, None),
        EveusSensor(entry, "substate", "Substate", None, None),
        EveusSensor(entry, "current_set", "Current Set", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
        EveusSensor(entry, "volt_meas1", "Voltage L1", UnitOfVoltage.VOLT, SensorDeviceClass.VOLTAGE),
        EveusSensor(entry, "cur_meas1", "Current L1", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
        EveusSensor(entry, "power_meas", "Power", UnitOfPower.KILO_WATT, SensorDeviceClass.POWER),
        EveusSensor(entry, "temperature1", "Box Temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
        EveusSensor(entry, "temperature2", "Plug Temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
        EveusSensor(entry, "ground", "Ground", None, None),
        EveusSensor(entry, "ground_ctrl", "Ground Control", None, None),
        EveusSensor(entry, "ai_voltage", "Adaptive Voltage", UnitOfVoltage.VOLT, SensorDeviceClass.VOLTAGE),
        EveusSensor(entry, "session_time", "Session Duration (sec)", UnitOfTime.SECONDS, SensorDeviceClass.DURATION),
        EveusSensor(entry, "session_time_formatted", "Session Duration", None, None),
        EveusSensor(entry, "session_energy", "Session Energy", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
        EveusSensor(entry, "total_energy", "Total Energy", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
        EveusSensor(entry, "ai_status", "Adaptive Mode", None, None),
        EveusSensor(entry, "system_time", "System Time", None, None),
        # Добавьте остальные сенсоры по аналогии...
    ]
    async_add_entities(sensors, True)

class EveusSensor(SensorEntity):
    """Representation of a Eveus sensor."""

    def __init__(self, entry, sensor_type, name, unit, device_class):
        """Initialize the sensor."""
        self._entry = entry
        self._sensor_type = sensor_type
        self._attr_name = f"{entry.data['name']} {name}"
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = SensorStateClass.MEASUREMENT if unit else None

    async def async_update(self):
        """Fetch new state data for the sensor."""
        data = await self._fetch_data()  # Этот метод нужно реализовать в __init__.py
        if not data:
            return

        if self._sensor_type == "evse_enabled":
            self._attr_native_value = "Yes" if data.get(ATTR_EVSE_ENABLED) == 1 else "No"
        
        elif self._sensor_type == "state":
            state_num = data.get(ATTR_STATE)
            self._attr_native_value = STATE_MAPPING.get(state_num, "Unknown")
        
        elif self._sensor_type == "substate":
            state_num = data.get(ATTR_STATE)
            substate_num = data.get(ATTR_SUB_STATE)
            if state_num == 7:  # Error state
                self._attr_native_value = SUBSTATE_ERROR_MAPPING.get(substate_num, "Unknown")
            else:
                self._attr_native_value = SUBSTATE_NORMAL_MAPPING.get(substate_num, "Unknown")
        
        elif self._sensor_type == "current_set":
            self._attr_native_value = data.get(ATTR_CURRENT_SET)
        
        elif self._sensor_type == "session_time_formatted":
            seconds = data.get(ATTR_SESSION_TIME)
            if seconds is not None:
                hours, remainder = divmod(seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                self._attr_native_value = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
        
        # Добавьте обработку остальных сенсоров по аналогии...