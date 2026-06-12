from __future__ import annotations

from .base import BaseCharger

V1_STATE_MAP = {
    0: "No data",    1: "Ready",              2: "Waiting",
    3: "Charging",   4: "Charging",           5: "Charging",
    6: "Charging",   7: "Current Leak",       8: "CPU ERROR",
    9: "No Ground",  10: "Overheat Plug",     11: "Overheat Relay",
    12: "OverCurrent", 13: "OverVoltage",     14: "UnderVoltage",
    15: "Limited By Time",    16: "Limited By Energy",
    17: "Limited By Money",   18: "Limited By Schedule1",
    19: "Limited By Schedule2", 20: "Disabled By User",
    21: "Relay Stuck",          22: "Limited By AI Mode",
}

AI_MODE_MAP = {0: "Off", 1: "Voltage", 2: "Tesla (auto)", 3: "Power"}


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
        return {"Off": 0, "Voltage": 1}

    @property
    def capabilities(self) -> set:
        return {
            "evseEnabled", "state", "currentSet", "curDesign",
            "curMeas1", "voltMeas1", "powerMeas",
            "temperature1", "temperature2",
            "aiStatus", "aiVoltage",
            "ground", "groundCtrl",
            "sessionTime", "sessionEnergy", "totalEnergy",
            "systemTime", "leakValue", "newsessiontime",
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
        raw["state"] = V1_STATE_MAP.get(int(raw.get("state", 0)), "Unknown")
        raw["aiStatus"] = AI_MODE_MAP.get(int(raw.get("aiStatus", 0)), "Unknown")
        # systemTime stays as "HH:MM:SS" string
        # newsessiontime: sessionTime seconds → "HH:MM:SS"
        secs = int(raw.get("sessionTime", 0))
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        raw["newsessiontime"] = f"{h:02d}:{m:02d}:{s:02d}"
        return raw
