from __future__ import annotations

from datetime import datetime, timezone

from .base import BaseCharger

V2_STATE_MAP = {
    0: "Startup",   1: "System Test",   2: "Standby",
    3: "Connected", 4: "Charging",      5: "Charge Complete",
    6: "Paused",    7: "Error",
}

V2_SUBSTATE_ERROR_MAP = {
    0: "No Error",          1: "Grounding Error",       2: "Current Leak High",
    3: "Relay Error",       4: "Current Leak Low",      5: "Box Overheat",
    6: "Plug Overheat",     7: "Pilot Error",           8: "Low Voltage",
    9: "Diode Error",      10: "Overcurrent",          11: "Interface Timeout",
    12: "Software Failure", 13: "GFCI Test Failure",   14: "High Voltage",
}

V2_SUBSTATE_LIMIT_MAP = {
    0: "No Limits",              1: "Limited by User",           2: "Energy Limit",
    3: "Time Limit",             4: "Cost Limit",                5: "Schedule 1 Limit",
    6: "Schedule 1 Energy Limit", 7: "Schedule 2 Limit",        8: "Schedule 2 Energy Limit",
    9: "Waiting for Activation", 10: "Paused by Adaptive Mode",
}

AI_MODE_MAP = {0: "Off", 1: "Voltage", 2: "Tesla (auto)", 3: "Power"}


class ChargerV2(BaseCharger):
    """API v2 – GBT."""

    async def get_status(self) -> dict:
        return await self._request("POST", "/main")

    async def set_current(self, value: int) -> None:
        await self._request(
            "POST", "/pageEvent",
            data=f"currentSet={value:02d}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    async def set_ai_mode(self, mode: int) -> None:
        await self._request(
            "POST", "/pageEvent",
            data=f"pageevent=evseEnabled&aiMode={mode}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    async def set_enabled(self, enabled: bool) -> None:
        # V2: 0 = start charging, 1 = stop charging
        value = 0 if enabled else 1
        await self._request(
            "POST", "/pageEvent",
            data=f"evseEnabled={value}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    async def sync_time(self) -> None:
        ts = int(datetime.now(tz=timezone.utc).timestamp())
        await self._request(
            "POST", "/pageEvent",
            data=f"systemTime={ts}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

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
        return {"Off": 0, "Voltage": 1, "Tesla (auto)": 2, "Power": 3}

    @property
    def capabilities(self) -> set:
        return {
            "evseEnabled", "state", "subState", "currentSet", "curDesign",
            "curMeas1", "voltMeas1", "powerMeas",
            "temperature1", "temperature2",
            "aiStatus", "aiVoltage",
            "ground", "groundCtrl",
            "sessionTime", "sessionEnergy", "totalEnergy",
            "systemTime", "leakValue", "newsessiontime",
            "vBat", "RSSI",
            "IEM1", "IEM2",
            "sync_time",
        }

    def transform_data(self, raw: dict) -> dict:
        raw = dict(raw)
        state_num = int(raw.get("state", 0))
        raw["state"] = V2_STATE_MAP.get(state_num, "Unknown")
        # subState depends on whether we're in error state
        substate_num = raw.get("subState")
        if substate_num is None:
            raw["subState"] = "unknown"
        else:
            mapper = V2_SUBSTATE_ERROR_MAP if state_num == 7 else V2_SUBSTATE_LIMIT_MAP
            raw["subState"] = mapper.get(int(substate_num), "Unknown")
        raw["aiStatus"] = AI_MODE_MAP.get(int(raw.get("aiStatus", 0)), "Unknown")
        # systemTime: unix timestamp → "DD.MM.YYYY HH:MM:SS"
        sys_time = raw.get("systemTime")
        if sys_time:
            try:
                dt = datetime.fromtimestamp(int(sys_time), tz=timezone.utc)
                raw["systemTime"] = dt.strftime("%d.%m.%Y %H:%M:%S")
            except (ValueError, OSError):
                pass
        # newsessiontime: sessionTime seconds → "HH:MM:SS"
        secs = int(raw.get("sessionTime", 0))
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        raw["newsessiontime"] = f"{h:02d}:{m:02d}:{s:02d}"
        return raw
