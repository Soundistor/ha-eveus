from __future__ import annotations

from datetime import UTC, datetime

from .base import AI_MODE_MAP, BaseCharger, as_enum_int, blank_absent_temperature

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
    9: "external_limit",        10: "paused_by_adaptive_mode",
}

class ChargerV2(BaseCharger):
    """API v2 – Eveus."""

    async def set_enabled(self, enabled: bool) -> None:
        # V2: 0 = start charging, 1 = stop charging
        await self._post_page_event(f"evseEnabled={0 if enabled else 1}")

    async def async_check_credentials(self) -> None:
        """Probe the one handler that enforces Basic auth — see BaseCharger.

        "/" is the static-file handler, and the only place this firmware checks
        credentials. Measured on R3.05.4 (2026-08-13): a wrong password answers
        401 in 0.13 s, while the same password on POST /main answers 200. Not
        done for V1 — that generation was never measured this way.
        """
        await self._request_text("GET", "/")

    async def sync_time(self) -> None:
        ts = int(datetime.now(tz=UTC).timestamp())
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

    # Closed on purpose, and shorter than "every numeric key in capabilities".
    # Left out deliberately: state/subState/aiStatus are mapped to strings
    # before anything reads them; systemTime/timeMsg/timeZone have their own
    # handling below and a drop would break the absent-clock contract;
    # evseEnabled/ground/groundCtrl are 0/1 flags compared as integers by
    # switch.py and binary_sensor.py. minCurrent is here although it is not a
    # capability: number.py derives the entity's min from it, and HA runs
    # floor/ceil on that, which raise on NaN.
    numeric_fields = (
        "currentSet", "curDesign", "curMeas1", "voltMeas1", "powerMeas",
        "temperature1", "temperature2", "aiVoltage", "aiModecurrent",
        "sessionTime", "sessionEnergy", "totalEnergy", "leakValue",
        "vBat", "RSSI", "IEM1", "IEM2", "minCurrent",
    )

    @property
    def capabilities(self) -> set:
        return {
            "evseEnabled", "state", "subState", "currentSet", "curDesign",
            "curMeas1", "voltMeas1", "powerMeas",
            "temperature1", "temperature2",
            "aiStatus", "aiVoltage", "aiModecurrent",
            "ground", "groundCtrl",
            "sessionTime", "sessionEnergy", "totalEnergy",
            "systemTime", "leakValue",
            "vBat", "RSSI",
            "IEM1", "IEM2",
            "sync_time",
            # Charging can be started AND stopped over HTTP — V1 cannot stop.
            "charge_switch",
        }

    def transform_data(self, raw: dict) -> dict:
        raw = dict(raw)
        state_num = as_enum_int(raw.get("state", 0))
        raw["state"] = V2_STATE_MAP.get(state_num, "unknown")
        # subState depends on whether we're in error state
        substate_num = raw.get("subState")
        if substate_num is None or state_num is None:
            # Without a readable state we cannot pick a map: the error map only
            # applies on a proven state_num == 7, and defaulting to the limit map
            # would read an unknown frame's subState as a charging *limit*.
            raw["subState"] = "unknown"
        else:
            mapper = V2_SUBSTATE_ERROR_MAP if state_num == 7 else V2_SUBSTATE_LIMIT_MAP
            raw["subState"] = mapper.get(as_enum_int(substate_num), "unknown")
        raw["aiStatus"] = AI_MODE_MAP.get(as_enum_int(raw.get("aiStatus", 0)), "unknown")
        for key in ("temperature1", "temperature2"):
            if key in raw:
                raw[key] = blank_absent_temperature(raw[key])
        # AFTER the sentinel is blanked, so a -60 "sensor absent" reading stays
        # present as None instead of having its key removed — consumers read
        # through .get either way, but three tests pin the key being there.
        self._drop_unparseable_numerics(raw)
        # systemTime is NOT an absolute UTC epoch: the station sends
        # UTC + timeZone*3600, i.e. its own local wall clock encoded as an
        # epoch. Subtract the offset to get the real instant, otherwise
        # time_drift reports a permanent offset equal to the configured
        # timezone on a perfectly healthy clock. (The write direction is the
        # opposite and already correct — sync_time sends true UTC and the
        # station adds the offset itself.)
        # timeMsg == 1 means the station's clock is invalid (typically a dead
        # RTC backup battery) — systemTime is then garbage and must not be
        # decoded at all, or time_drift reports a huge fake offset instead of
        # unknown.
        sys_time = raw.get("systemTime")
        if as_enum_int(raw.get("timeMsg", 0)) == 1:
            raw["systemTime"] = None
        # `is not None` rather than truthiness, as on V1: "", [] and {} are
        # falsy and were left in the frame untouched, reaching a TIMESTAMP
        # entity. An epoch of 0 is also falsy and is a real reading.
        elif sys_time is not None:
            try:
                offset = int(raw.get("timeZone", 0)) * 3600
                raw["systemTime"] = datetime.fromtimestamp(int(sys_time) - offset, tz=UTC)
            # OverflowError belongs here as much as the rest: int(inf) raises
            # it, and so does an epoch beyond the platform's range. These two
            # fields are left out of numeric_fields on the grounds that they
            # handle their own garbage — which was true of NaN, where int()
            # raises ValueError, and false of Infinity. Uncaught it escapes
            # transform_data, the coordinator reports UpdateFailed, and EVERY
            # entity goes unavailable for as long as the station keeps sending
            # it: worse than the single-sensor damage this file exists to stop.
            except (ValueError, OSError, TypeError, OverflowError):
                raw["systemTime"] = None
        return raw
