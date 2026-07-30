from __future__ import annotations

from datetime import datetime

from .base import AI_MODE_MAP, BaseCharger, blank_absent_temperature

# The station's own enum, read off the web UI it serves (EnergyStar V5.23) and
# confirmed live on 2026-07-30: unplugged reads 12, a plugged car that is not
# charging reads 9. The map this replaced came from the project ha-eveus was
# forked from, whose config was taken from a V2-generation station — it agreed
# with V1 only on 0 and 6, so a plugged car showed "No Ground" and an unplugged
# one "Overcurrent". Codes 1..5, 7, 8, 10 and 11 do not exist on V1.
V1_STATE_MAP = {
    0: "no_data",        6: "charging",       9: "waiting",
    12: "ready",        13: "delayed_start", 14: "overcurrent",
    15: "overvoltage",  16: "current_leak",  17: "station_error",
    18: "overheat",     19: "locked",        20: "no_ground",
    21: "overheat_plug", 22: "undervoltage",
}


class ChargerV1(BaseCharger):
    """API v1 – Eveus."""

    # V1 answers every /pageEvent write with HTTP 200, Content-Type text/plain
    # and an EMPTY body — identically for an applied write and for a parameter
    # name that does not exist (measured on EnergyStar V5.23, 2026-07-30). There
    # is no acknowledgement to check, so the HTTP status is all we have; the
    # coordinator's next poll is what actually confirms the new value.
    write_ack = None

    async def set_enabled(self, enabled: bool) -> None:
        await self._post_page_event(f"evseEnabled={1 if enabled else 0}")

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
        for key in ("temperature1", "temperature2"):
            if key in raw:
                raw[key] = blank_absent_temperature(raw[key])
        # systemTime: device sends a wall-clock "HH:MM:SS" (no date, no tz).
        # Return it as a naive datetime (today's date, device wall-clock) and let
        # the coordinator localize it to HA's configured timezone — this package
        # loads without homeassistant, so dt_util isn't available here, and using
        # the OS-local tz would make the derived time_drift wrong when HA runs in
        # a different timezone than the host.
        sys_time = raw.get("systemTime")
        if sys_time:
            try:
                t = datetime.strptime(sys_time, "%H:%M:%S").time()
                raw["systemTime"] = datetime.now().replace(
                    hour=t.hour, minute=t.minute, second=t.second, microsecond=0
                )
            except ValueError:
                raw["systemTime"] = None
        return raw
