from __future__ import annotations

from datetime import datetime
import re

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
        """Start charging. V1 cannot be stopped remotely — say so, don't pretend.

        Sending `evseEnabled=0` mid-session was tested live (2026-07-30, raw
        curl, bypassing the integration): the station keeps charging and keeps
        reporting evseEnabled=1. Its own web UI never sends that write on its
        own either — it only appears when the user hands control to the
        schedule, so stopping is schedule-driven in this firmware, not a flag.
        Since V1 acknowledges nothing (see write_ack), posting it anyway would
        report success for something that did not happen.
        """
        if not enabled:
            # Lazy import: see BaseCharger._get_session.
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(
                f"Charger {self.ip} (V1) cannot stop charging remotely: this "
                "firmware has no stop command. End the session by unplugging "
                "the car, or let a time/energy limit expire."
            )
        await self._post_page_event("evseEnabled=1")

    async def async_load_sw_version(self) -> None:
        """V1 reports no version in /main — take it from the page footer.

        The station serves its own UI at "/", whose footer reads e.g.
        "EnergyStar V5.23". One GET at setup fills a device page that would
        otherwise show no firmware at all.
        """
        try:
            page = await self._request_text("GET", "/")
        except Exception:  # a missing version must never break setup
            return
        match = re.search(r"EnergyStar\s*V[\d.]+", page)
        if match:
            self.sw_version = match.group(0)

    async def sync_time(self) -> None:
        """Set the station's clock to Home Assistant's local wall clock.

        V1 stores exactly the epoch it is given and applies no offset when it
        renders the clock: writing a UTC epoch made it display UTC, even though
        its own `timeZone` field said 2 (measured 2026-07-30). So the number to
        send is local wall-clock seconds — UTC epoch plus the local offset —
        and the station's `timeZone` must not be trusted for this. Its own web
        UI does the same arithmetic in the browser.
        """
        # Lazy import: see BaseCharger._get_session. dt_util.now() is HA's
        # configured timezone, which is what the user sees in the UI — not the
        # host's, which may differ.
        from homeassistant.util import dt as dt_util

        local = dt_util.now()
        await self._post_page_event(
            f"systemTime={int(local.timestamp() + local.utcoffset().total_seconds())}"
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
            "aiStatus", "aiVoltage", "aiModecurrent",
            "ground", "groundCtrl",
            "sessionTime", "sessionEnergy", "totalEnergy",
            "systemTime", "leakValue",
            "sync_time",
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
