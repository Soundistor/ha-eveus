from __future__ import annotations

from datetime import datetime
import logging
import re

from .base import (
    AI_MODE_MAP,
    BaseCharger,
    as_enum_int,
    as_float,
    blank_absent_temperature,
)

_LOGGER = logging.getLogger(__name__)

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

    # Set on the instance the first time a garbage numeric field is seen.
    _warned_garbage_numeric = False

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
        except Exception as exc:  # a missing version must never break setup
            status = getattr(exc, "status", None)
            self.sw_version_error = (
                f"{type(exc).__name__}"
                + (f" (HTTP {status})" if status is not None else "")
            )
            return
        match = re.search(r"EnergyStar\s*V[\d.]+", page)
        if not match:
            # The GET succeeded, so there is no exception to report — without
            # this branch a changed footer stays as invisible as it was before
            # this method recorded anything at all. The page itself is never
            # stored: it carries the station's identifiers, and this value is
            # surfaced in diagnostics.
            self.sw_version_error = "version pattern not found in page"
            return
        self.sw_version = match.group(0)
        self.sw_version_error = None

    async def async_check_credentials(self) -> None:
        """Probe the one handler that enforces Basic auth — see BaseCharger.

        The base class withholds this check from generations whose auth path was
        never measured. V1's now has been, twice on the same unit: GET / answers
        401 without credentials and 200 with the correct ones, while POST /main
        answers 200 to any password (2026-08-18, and again 2026-09-01 when the
        owner's Reconfigure with the station's real web password made
        `sw_version` appear as "EnergyStar V5.23" within one or two polls).

        This matters more on V1 than on V2: `async_load_sw_version` above is the
        integration's only call that needs authorisation at all, and it swallows
        its own failure, so a wrong password shows up as nothing whatsoever — no
        firmware row on the device page, no log line. The form is the one place
        the user can still fix the input.
        """
        await self._request_text("GET", "/")

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

    def _warn_once_on_garbage(self, raw: dict, numeric: dict) -> None:
        """Name the bad fields once per charger, not once per poll.

        A poll runs every 30-60 s; a station that starts emitting garbage would
        otherwise fill the log with the same line forever. An absent key is not
        garbage — only a key that is present and unparseable is reported.
        """
        if self._warned_garbage_numeric:
            return
        bad = [key for key, value in numeric.items() if value is None and key in raw]
        if not bad:
            return
        self._warned_garbage_numeric = True
        _LOGGER.warning(
            "%s: unparseable numeric field(s) in /main, reported as unknown: %s",
            self.ip,
            ", ".join(f"{key}={raw[key]!r}" for key in bad),
        )

    def transform_data(self, raw: dict) -> dict:
        raw = dict(raw)
        # A key is written only when there is a real number behind it. Writing
        # 0.0 for an absent or unparseable field is worse than writing nothing:
        # the sensor reports a confident zero, and every consumer that guards on
        # `is not None` (SessionEnergySensor's last_reset, DailyEnergySensor's
        # baseline, the coordinator's _live_energy) acts on it. Dropping the key
        # instead lets sensor.py's .get(key) fold it to unknown.
        numeric = {
            key: as_float(raw.get(key))
            for key in ("voltMeas1", "curMeas1", "sessionEnergy", "totalEnergy")
        }
        self._warn_once_on_garbage(raw, numeric)
        volt = numeric["voltMeas1"]
        cur = numeric["curMeas1"]  # 0.1 A units
        # powerMeas = V × I × 0.1  (raw curMeas1 in 0.1A units), derived only
        # when both factors are real
        if volt is not None and cur is not None:
            raw["powerMeas"] = round(volt * cur * 0.1, 1)
        else:
            raw.pop("powerMeas", None)
        # voltMeas1 is not rescaled and stays pass-through when it parses — the
        # guard only removes it when it does not, so the sensor reads unknown
        # instead of a string or a fabricated zero.
        if volt is None:
            raw.pop("voltMeas1", None)
        # Scale raw integer values to real units
        _set_or_drop(raw, "curMeas1", None if cur is None else round(cur * 0.1, 1))
        for key in ("sessionEnergy", "totalEnergy"):
            value = numeric[key]
            _set_or_drop(raw, key, None if value is None else round(value * 0.1, 3))
        # Map enums to strings
        raw["state"] = V1_STATE_MAP.get(as_enum_int(raw.get("state", 0)), "unknown")
        raw["aiStatus"] = AI_MODE_MAP.get(as_enum_int(raw.get("aiStatus", 0)), "unknown")
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


def _set_or_drop(raw: dict, key: str, value) -> None:
    """Write the key, or remove it entirely — never leave a None behind."""
    if value is None:
        raw.pop(key, None)
    else:
        raw[key] = value
