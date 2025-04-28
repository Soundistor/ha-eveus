DOMAIN = "eveus"
DEFAULT_NAME = "Eveus"
DEFAULT_HOST = "http://192.168.0.1"
DEFAULT_USERNAME = "eveus"
DEFAULT_PASSWORD = "eveus"
DEFAULT_METHOD = "POST"
DEFAULT_SCAN_INTERVAL = 30  # seconds

# Атрибуты из REST-запроса
ATTR_EVSE_ENABLED = "evseEnabled"
ATTR_STATE = "state"
ATTR_SUB_STATE = "subState"
ATTR_CURRENT_SET = "currentSet"
ATTR_CUR_DESIGN = "curDesign"
ATTR_TYPE_EVSE = "typeEvse"
ATTR_TYPE_RELAY = "typeRelay"
ATTR_AI_MODE_CURRENT = "aiModecurrent"
ATTR_AI_STATUS = "aiStatus"
ATTR_AI_VOLTAGE = "aiVoltage"
ATTR_AI_PARAMETER = "aiPatameter"
ATTR_GROUND = "ground"
ATTR_GROUND_CTRL = "groundCtrl"
ATTR_TIMER_TYPE = "timerType"
ATTR_LIMITS_STATUS = "limitsStatus"
ATTR_TIME_LIMIT = "timeLimit"
ATTR_ENERGY_LIMIT = "energyLimit"
ATTR_MONEY_LIMIT = "moneyLimit"
ATTR_TARIF = "tarif"
ATTR_START_SCHEDULE1 = "startSchedule1"
ATTR_STOP_SCHEDULE1 = "stopSchedule1"
ATTR_CURRENT_SCHEDULE1 = "currentSchedule1"
ATTR_ENERGY_SCHEDULE1 = "energySchedule1"
ATTR_TARIF_SCHEDULE1 = "tarifSchedule1"
ATTR_START_SCHEDULE2 = "startSchedule2"
ATTR_STOP_SCHEDULE2 = "stopSchedule2"
ATTR_CURRENT_SCHEDULE2 = "currentSchedule2"
ATTR_ENERGY_SCHEDULE2 = "energySchedule2"
ATTR_TARIF_SCHEDULE2 = "tarifSchedule2"
ATTR_SESSION_ENERGY = "sessionEnergy"
ATTR_SESSION_TIME = "sessionTime"
ATTR_TOTAL_ENERGY = "totalEnergy"
ATTR_SYSTEM_TIME = "systemTime"
ATTR_TIME_ZONE = "timeZone"
ATTR_CUR_MEAS1 = "curMeas1"
ATTR_CUR_MEAS2 = "curMeas2"
ATTR_CUR_MEAS3 = "curMeas3"
ATTR_VOLT_MEAS1 = "voltMeas1"
ATTR_VOLT_MEAS2 = "voltMeas2"
ATTR_VOLT_MEAS3 = "voltMeas3"
ATTR_TEMPERATURE1 = "temperature1"
ATTR_TEMPERATURE2 = "temperature2"
ATTR_LEAK_VALUE = "leakValue"
ATTR_V_BAT = "vBat"
ATTR_POWER_MEAS = "powerMeas"
ATTR_STA_IP_ADDRESS = "STA_IP_Addres"

# Маппинги для состояний и подсостояний
STATE_MAPPING = {
    0: "Startup",
    1: "System Test",
    2: "Standby",
    3: "Connected",
    4: "Charging",
    5: "Charge Complete",
    6: "Paused",
    7: "Error"
}

SUBSTATE_ERROR_MAPPING = {
    0: "No Error",
    1: "Grounding Error",
    2: "Current Leak High",
    3: "Relay Error",
    4: "Current Leak Low",
    5: "Box Overheat",
    6: "Plug Overheat",
    7: "Pilot Error",
    8: "Low Voltage",
    9: "Diode Error",
    10: "Overcurrent",
    11: "Interface Timeout",
    12: "Software Failure",
    13: "GFCI Test Failure",
    14: "High Voltage"
}

SUBSTATE_NORMAL_MAPPING = {
    0: "No Limits",
    1: "Limited by User",
    2: "Energy Limit",
    3: "Time Limit",
    4: "Cost Limit",
    5: "Schedule 1 Limit",
    6: "Schedule 1 Energy Limit",
    7: "Schedule 2 Limit",
    8: "Schedule 2 Energy Limit",
    9: "Waiting for Activation",
    10: "Paused by Adaptive Mode"
}

AI_STATUS_MAPPING = {
    0: "Off",
    1: "Voltage",
    2: "Tesla (auto)",
    3: "Power"
}