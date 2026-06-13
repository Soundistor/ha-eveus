from __future__ import annotations

from datetime import datetime

from .base import BaseCharger

V1_STATE_MAP = {
    0: "no_data",      1: "ready",                  2: "waiting",
    3: "charging",     4: "charging",               5: "charging",
    6: "charging",     7: "current_leak",            8: "cpu_error",
    9: "no_ground",   10: "overheat_plug",          11: "overheat_relay",
    12: "overcurrent", 13: "overvoltage",            14: "undervoltage",
    15: "limited_by_time",    16: "limited_by_energy",
    17: "limited_by_money",   18: "limited_by_schedule1",
    19: "limited_by_schedule2", 20: "disabled_by_user",
    21: "relay_stuck",           22: "limited_by_ai_mode",
}

AI_MODE_MAP = {0: "off", 1: "voltage", 2: "tesla_auto", 3: "power"}


class ChargerV1(BaseCharger):
    """API v1 – Bolt/Eveus."""

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
        value = 1 if enabled else 0
        await self._request(
            "POST", "/pageEvent",
            data=f"evseEnabled={value}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def is_charging_active(self, enabled_value) -> bool:
        return enabled_value == 1

    @property
    def min_current(self) -> int:
        return 7

    @property
    def model_name(self) -> str:
        return "V1"

    @property
    def ai_modes(self) -> dict:
        return {"off": 0, "voltage": 1}

    @property
    def capabilities(self) -> set:
        return {
            "evseEnabled", "state", "currentSet", "curDesign",
            "curMeas1", "voltMeas1", "powerMeas",
            "temperature1", "temperature2",
            "aiStatus", "aiVoltage",
            "ground", "groundCtrl",
            "sessionTime", "sessionEnergy", "totalEnergy",
            "systemTime", "leakValue",
        }

    def transform_data(self, raw: dict) -> dict:
        raw = dict(raw)
        # powerMeas = V × I × 0.1  (raw curMeas1 in 0.1A units)
        v = int(raw.get("voltMeas1", 0))
        i = int(raw.get("curMeas1", 0))
        raw["powerMeas"] = round(v * i * 0.1, 1)
        # Scale raw integer values to real units
        raw["curMeas1"] = round(int(raw.get("curMeas1", 0)) * 0.1, 1)
        raw["sessionEnergy"] = round(int(raw.get("sessionEnergy", 0)) * 0.1, 3)
        raw["totalEnergy"] = round(int(raw.get("totalEnergy", 0)) * 0.1, 3)
        # Map enums to strings
        raw["state"] = V1_STATE_MAP.get(int(raw.get("state", 0)), "unknown")
        raw["aiStatus"] = AI_MODE_MAP.get(int(raw.get("aiStatus", 0)), "unknown")
        # systemTime: "HH:MM:SS" from device → timezone-aware datetime (today's local date)
        sys_time = raw.get("systemTime")
        if sys_time:
            try:
                t = datetime.strptime(sys_time, "%H:%M:%S").time()
                raw["systemTime"] = datetime.now().astimezone().replace(
                    hour=t.hour, minute=t.minute, second=t.second, microsecond=0
                )
            except ValueError:
                raw["systemTime"] = None
        return raw
