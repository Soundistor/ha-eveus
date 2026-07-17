from __future__ import annotations

from datetime import datetime, timezone

from .base import AI_MODE_MAP, BaseCharger

V2_STATE_MAP = {
    0: "startup",      1: "system_test",      2: "standby",
    3: "connected",    4: "charging",         5: "charge_complete",
    6: "paused",       7: "error",
}

V2_SUBSTATE_ERROR_MAP = {
    0: "no_error",           1: "grounding_error",        2: "current_leak_high",
    3: "relay_error",        4: "current_leak_low",       5: "box_overheat",
    6: "plug_overheat",      7: "pilot_error",            8: "low_voltage",
    9: "diode_error",       10: "overcurrent",           11: "interface_timeout",
   12: "software_failure",  13: "gfci_test_failure",     14: "high_voltage",
}

V2_SUBSTATE_LIMIT_MAP = {
    0: "no_limits",               1: "limited_by_user",           2: "energy_limit",
    3: "time_limit",              4: "cost_limit",                5: "schedule1_limit",
    6: "schedule1_energy_limit",  7: "schedule2_limit",          8: "schedule2_energy_limit",
    9: "waiting_for_activation", 10: "paused_by_adaptive_mode",
}

class ChargerV2(BaseCharger):
    """API v2 – GBT."""

    async def set_enabled(self, enabled: bool) -> None:
        # V2: 0 = start charging, 1 = stop charging
        await self._post_page_event(f"evseEnabled={0 if enabled else 1}")

    async def sync_time(self) -> None:
        ts = int(datetime.now(tz=timezone.utc).timestamp())
        await self._post_page_event(f"systemTime={ts}")

    def is_charging_active(self, enabled_value) -> bool:
        return enabled_value == 0

    @property
    def min_current(self) -> int:
        return 6

    @property
    def model_name(self) -> str:
        return "V2"

    @property
    def ai_modes(self) -> dict:
        return {"off": 0, "voltage": 1, "tesla_auto": 2, "power": 3}

    @property
    def capabilities(self) -> set:
        return {
            "evseEnabled", "state", "subState", "currentSet", "curDesign",
            "curMeas1", "voltMeas1", "powerMeas",
            "temperature1", "temperature2",
            "aiStatus", "aiVoltage",
            "ground", "groundCtrl",
            "sessionTime", "sessionEnergy", "totalEnergy",
            "systemTime", "leakValue",
            "vBat", "RSSI",
            "IEM1", "IEM2",
            "sync_time",
        }

    def transform_data(self, raw: dict) -> dict:
        raw = dict(raw)
        state_num = int(raw.get("state", 0))
        raw["state"] = V2_STATE_MAP.get(state_num, "unknown")
        # subState depends on whether we're in error state
        substate_num = raw.get("subState")
        if substate_num is None:
            raw["subState"] = "unknown"
        else:
            mapper = V2_SUBSTATE_ERROR_MAP if state_num == 7 else V2_SUBSTATE_LIMIT_MAP
            raw["subState"] = mapper.get(int(substate_num), "unknown")
        raw["aiStatus"] = AI_MODE_MAP.get(int(raw.get("aiStatus", 0)), "unknown")
        # systemTime: unix timestamp → UTC datetime object (device_class=TIMESTAMP)
        sys_time = raw.get("systemTime")
        if sys_time:
            try:
                raw["systemTime"] = datetime.fromtimestamp(int(sys_time), tz=timezone.utc)
            except (ValueError, OSError):
                raw["systemTime"] = None
        return raw
