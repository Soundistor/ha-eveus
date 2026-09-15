"""DataUpdateCoordinator – единственная точка получения данных от зарядки."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .charger.base import BaseCharger, as_float
from .const import (
    DOMAIN,
    EVENT_CHARGING_STARTED,
    EVENT_SESSION_ENDED,
    SESSION_ACTIVE_STATES,
    session_transition,
)
from .entity import firmware_version

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EveusData:
    """Runtime data stored on the config entry (entry.runtime_data)."""

    charger: BaseCharger
    coordinator: ChargerCoordinator
    prefix: str


type EveusConfigEntry = ConfigEntry[EveusData]

# Charger is unreachable (powered off / unplugged / off the network). This is a
# normal state for this device — surface it as "unavailable" entities only, not
# as a repair issue the user has to act on.
UNREACHABLE_ERRORS = (aiohttp.ClientConnectionError, asyncio.TimeoutError)

# If more than this elapses between two successful polls, the charger/HA was
# offline long enough that a state remembered from before the gap is no longer a
# valid baseline — replaying its transition would fire a stale session_ended
# with pre-offline figures. Reset the baseline instead. A short blip (one or two
# missed polls, well under this) is preserved, so a session that ends across a
# brief network hiccup is still reported.
STALE_STATE_AFTER = timedelta(minutes=15)

# /main serves cached values, and a write needs a couple of poll cycles before
# it shows up there: the station's own web client discards exactly the next 2
# responses after every write (3 after a current change), globally rather than
# per field. Refreshing the instant a write returns therefore reads the OLD
# value back and undoes what the user just did on screen. Wait this long first.
WRITE_SETTLE = timedelta(seconds=3)

# Counters that only ever grow, short of a reset the user asked for. A step down
# in any of them is either the station dropping an unflushed tail after a
# restart, or the counter not being loaded from flash yet — both measured on V1.
# sessionEnergy is deliberately NOT here: it legitimately falls to zero at the
# start of every session, and the power-cut latch in _process_session_events is
# built on exactly that zero.
LIFETIME_COUNTERS = ("totalEnergy", "IEM1", "IEM2")

# How many consecutive frames must agree before a lower reading is believed.
# One frame is not enough (a reboot frame reads 0 and the next reads the real
# value again), and waiting is not free either: the station can lose a tail to
# flash permanently, and a guard that never believes a lower value would freeze
# the sensor until the counter climbed back past the old maximum.
COUNTER_CONFIRM_FRAMES = 2

# Same idea for the setpoint, and needed for the same reason in reverse: a
# station can genuinely sit below the generation minimum. V1's own UI accepts
# >= 6 on read while its slider starts at 7, the firmware range-checks nothing
# (KB-03 BUG-13), and a garbage write leaves currentSet at 0 until someone
# writes again (KB-04 §3.2) — on a station other people can reach. Without a
# streak the guard would hide that state forever behind `unknown` and repeat a
# "still loading from flash" warning every poll for a restart that never
# happened, which is the opposite of showing the user what the station is doing.
SETPOINT_CONFIRM_FRAMES = 2

# How many polls may try to fetch the firmware version before giving up until
# the next reload. V2 reports it in /main and never gets here; V1 needs a GET
# that can fail exactly when the station has only just come back up.
_SW_VERSION_MAX_ATTEMPTS = 3

# Firmware-level faults that bypass safety debounce in binary sensors. Every
# member must be a value some state map actually produces — see
# test_fault_states_all_come_from_a_state_map. cpu_error and relay_stuck used to
# sit here and no map ever emitted them.
FIRMWARE_FAULT_STATES = frozenset({
    "no_ground",                          # V1 main state
    "relay_error", "software_failure",    # V2 subState
    "pilot_error", "gfci_test_failure",   # V2 subState
    "grounding_error",                    # V2 subState — the fault the ground
                                          # binary sensor represents, so it must
                                          # not be the slowest one to confirm
})


class ChargerCoordinator(DataUpdateCoordinator[dict[str, Any]]):

    def __init__(
        self,
        hass: HomeAssistant,
        charger,
        entry_id,
        device_name,
        update_interval: int = 30,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=device_name,
            update_interval=timedelta(seconds=update_interval),
        )
        self.charger = charger
        self._entry_id = entry_id
        self._device_name = device_name
        self._prev_state = None
        self._last_success = None
        self._sw_version_loaded = False
        self._sw_version_attempts = 0
        self._device_version_written = False
        self._live_energy = None
        self._live_time = None
        self.last_session = None
        self._setpoint_dropped = 0
        self._counter_dropped = 0
        # RAM only, and knowingly so: after an HA restart the first frame is
        # believed whatever it says. Persisting it would buy the one case where
        # a blackout takes the station and HA together — a real gap, but not
        # worth a stored baseline that can itself go stale.
        self._last_counter: dict[str, float] = {}
        self._counter_low_streak: dict[str, int] = {}
        self._counter_low_since: dict[str, datetime] = {}
        self._setpoint_low_streak = 0
        self._setpoint_low_since: datetime | None = None
        # The lowest value confirmed as "the station really sits here", so a
        # further drop below it still has to prove itself.
        self._setpoint_floor: float | None = None

    @callback
    def schedule_refresh_after_write(self) -> None:
        """Refresh once the station has had time to apply a write.

        Deliberately not an immediate `async_request_refresh()` — see
        WRITE_SETTLE. Scheduled rather than awaited so the user's action
        returns at once instead of blocking on the settle time.
        """
        async_call_later(self.hass, WRITE_SETTLE.total_seconds(), self._refresh_now)

    async def _refresh_now(self, _now) -> None:
        await self.async_request_refresh()

    def _forget_stale_guard_evidence(self) -> None:
        """Drop half-finished guard evidence from before a long gap.

        Both guards confirm a reading by seeing it again after a real poll
        interval. A first low frame from before an outage and a low frame from
        after it are not that: they are two unrelated events, most likely a
        pre-gap anomaly and a boot artefact from the very restart that caused
        the gap. The elapsed-interval test would pass on arithmetic — the gap
        is minutes or hours — while failing on meaning, and confirm the new
        reading on its first frame.

        Runs BEFORE the guards, unlike the sibling reset of `_prev_state`
        further down `_async_update_data`: that one only has to be right by the
        time session events are processed, this one has to be right for the
        frame being guarded right now.
        """
        if self._last_success is None:
            return
        if dt_util.utcnow() - self._last_success <= STALE_STATE_AFTER:
            return
        self._setpoint_low_streak = 0
        self._setpoint_low_since = None
        self._counter_low_streak.clear()
        self._counter_low_since.clear()

    def _drop_implausible_setpoint(self, data: dict[str, Any]) -> None:
        """Drop a currentSet the station cannot legally have sent.

        The first frame after the station restarts carries values it has not
        loaded from flash yet. Measured 2026-09-10 on V1: currentSet read 0 in
        the same frame that read totalEnergy 0, then 12 a minute later, then 20.
        Zero is not a low setpoint, it is an impossible one — the station's
        service page offers 6/7/8 as the minimum and nothing below it can be
        selected.

        The floor is the generation constant, deliberately NOT
        `number.native_min_value`: that one reads `minCurrent` out of this same
        frame, and whether `minCurrent` survives a reboot frame has never been
        measured (on V1 the key does not exist at all). The constant is the
        lowest value the service page offers, so it is lenient — a station
        configured to 8 A still passes a 7 — but never wrong.

        Why a transient is worth dropping: the setpoint is control state, not a
        readout. Every automation that steps the current reads it first, so a
        zero either fails their conditions or becomes the base for the next
        step, and both failures are silent — a skipped condition or a template
        error, neither of which reaches the log.

        Only the low side is checked. `curDesign` bounds the top and comes out
        of the same suspect frame, so guarding against it would reintroduce the
        dependency this method exists to avoid.

        And only a *transient* one. A station can genuinely hold a value below
        the generation minimum — V1's own UI accepts >= 6 on read while its
        slider starts at 7, the firmware range-checks nothing (KB-03 BUG-13),
        and a garbage write leaves currentSet at 0 until someone writes again
        (KB-04 §3.2), on a station other people can reach. Refusing that state
        forever would replace it with `unknown` and repeat a "still loading
        from flash" warning every poll about a restart that never happened —
        hiding what the station is doing instead of showing it. So the same
        rule as the counters: after SETPOINT_CONFIRM_FRAMES frames in a row it
        is believed.
        """
        # as_float, not float(): nan survives float() and then compares False
        # against everything, so it would pass this check and poison every
        # automation that uses the setpoint as its base.
        value = as_float(data.get("currentSet"))
        if value is None:
            # Missing, or non-numeric garbage — a different problem with a
            # different fix. This guard is about a value that parses and is
            # still impossible.
            return
        if value >= self.charger.min_current:
            # Back in the normal range: forget everything, including a low
            # value confirmed earlier.
            self._setpoint_floor = None
            self._setpoint_low_streak = 0
            self._setpoint_low_since = None
            return

        floor = self._setpoint_floor
        if floor is not None and value >= floor:
            # Already-confirmed territory: the station has been sitting here
            # and the user has seen it. Do not make it prove the same value
            # over and over.
            self._setpoint_low_streak = 0
            self._setpoint_low_since = None
            return

        now = dt_util.utcnow()
        self._setpoint_low_streak += 1
        if self._setpoint_low_since is None:
            self._setpoint_low_since = now
        # Over a real poll interval, for the same reason as the counter guard:
        # a write schedules an extra poll 3 s later, and confirming on that one
        # would publish the boot zero to every automation that reads the
        # setpoint — the breakage this guard exists to prevent.
        if (
            self._setpoint_low_streak >= SETPOINT_CONFIRM_FRAMES
            and now - self._setpoint_low_since >= self.update_interval
        ):
            # Not a boot artefact: the station is really sitting there. Publish
            # it, and stop warning — the user needs to see the value to act on
            # it. Rebase on the confirmed value, exactly as the counter guard
            # rebases _last_counter: without this the streak and the timestamp
            # stay "long past the threshold" forever, so the NEXT drop — a real
            # boot zero hours later — confirms on its first frame and reaches
            # the automations untouched. The guard would switch itself off the
            # first time a station legitimately sat below the minimum.
            self._setpoint_floor = value
            self._setpoint_low_streak = 0
            self._setpoint_low_since = None
            return

        self._setpoint_dropped += 1
        _LOGGER.warning(
            "Holding back currentSet %s: below the %s A minimum this "
            "generation can be set to, and not yet confirmed by a second "
            "frame. Most likely the station is still loading it from flash "
            "after a restart",
            value,
            self.charger.min_current,
        )
        del data["currentSet"]

    def _drop_unconfirmed_counter_drops(self, data: dict[str, Any]) -> None:
        """Hold back a lifetime counter that stepped down, until it repeats.

        Two measured ways these counters go backwards, and they need the same
        treatment for different reasons:

          * the counter is not loaded from flash yet — 2026-09-10 on V1,
            totalEnergy read 0 and the real 119.8 came back one minute later;
          * the station dropped a tail it had not flushed — 2026-09-03,
            78.5 -> 77.9, and that one does NOT come back.

        Publishing either is expensive. `DailyEnergySensor` reads a value under
        its baseline as a counter reset and rebases, which turns a day's delta
        into the whole lifetime reading — measured, 134 kWh in a day on a 4.2 kW
        station. Long-term statistics keep whatever they were handed.

        So: hold a lower reading back, and believe it once a second frame in a
        row also reads low. The reboot zero dies on the first frame and never
        confirms; a permanent loss confirms on the next poll and the counter
        carries on from there instead of freezing until it climbs back.

        A 12 h continuous run on both stations (2026-09-13, ~24 900 samples at
        2 s) saw exactly one step down, straight after a gap and with the
        station reporting no_data — and none at all during uninterrupted
        polling, which is what makes a bare two-frame rule enough and a
        tolerance band unnecessary.
        """
        for key in LIFETIME_COUNTERS:
            value = as_float(data.get(key))
            if value is None:
                continue
            last = self._last_counter.get(key)
            if last is None or value >= last:
                self._last_counter[key] = value
                self._counter_low_streak[key] = 0
                self._counter_low_since.pop(key, None)
                continue

            now = dt_util.utcnow()
            streak = self._counter_low_streak.get(key, 0) + 1
            since = self._counter_low_since.setdefault(key, now)
            # Confirmation has to span a real poll interval, not just a second
            # frame. Any write to number/switch/select schedules an extra poll
            # WRITE_SETTLE (3 s) later and the Force Refresh button fires one
            # immediately, so counting frames alone lets two reads 3 s apart
            # confirm a zero — and the station's boot window is longer than
            # that (measured 2026-09-10: 0 at 07:00:37, the real value at
            # 07:01:37, so the window is somewhere under ~120 s and certainly
            # over 3). Believing it then would rebase on exactly the reading
            # this guard exists to refuse.
            if streak >= COUNTER_CONFIRM_FRAMES and now - since >= self.update_interval:
                # Confirmed by repetition over time: a real reset, or a tail
                # the station is never getting back. Carry on from here.
                self._last_counter[key] = value
                self._counter_low_streak[key] = 0
                self._counter_low_since.pop(key, None)
                continue

            self._counter_low_streak[key] = streak
            self._counter_dropped += 1
            _LOGGER.warning(
                "Holding back %s=%s: below the last known %s and not yet "
                "confirmed by a second frame",
                key,
                value,
                last,
            )
            del data[key]

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            raw = await self.charger.get_status()
            data = self.charger.transform_data(raw)
            self._forget_stale_guard_evidence()
            self._drop_implausible_setpoint(data)
            self._drop_unconfirmed_counter_drops(data)
            # V1 reports systemTime as a naive wall-clock time-of-day; localize it
            # to an absolute instant using HA's configured timezone (not the host
            # OS tz). V2 resolves its own offset in transform_data and hands us an
            # absolute UTC datetime — leave anything tz-aware untouched.
            st = data.get("systemTime")
            if isinstance(st, datetime) and st.tzinfo is None:
                data["systemTime"] = dt_util.now().replace(
                    hour=st.hour, minute=st.minute, second=st.second, microsecond=0
                )
            ir.async_delete_issue(self.hass, DOMAIN, f"device_error_{self._entry_id}")
            # Dynamic polling: 30s while charging, 60s otherwise
            self.update_interval = timedelta(
                seconds=30 if data.get("state") == "charging" else 60
            )
            now = dt_util.utcnow()
            if (
                self._last_success is not None
                and now - self._last_success > STALE_STATE_AFTER
            ):
                # Long gap since the last good poll: the charger was offline
                # long enough that the remembered state is stale. Drop the
                # baseline so this poll starts fresh and we don't replay a
                # transition that happened while offline.
                self._prev_state = None
            self._last_success = now
            await self._load_sw_version_once()
            self._write_sw_version_to_registry(data)
            self._process_session_events(data)
            return data
        except UNREACHABLE_ERRORS as exc:
            # Expected when the charger is unplugged/powered off — entities go
            # unavailable; don't raise a repair issue. A brief blip keeps the
            # baseline (see STALE_STATE_AFTER); only a long gap resets it.
            raise UpdateFailed(f"Charger unreachable: {exc}") from exc
        except Exception as exc:
            # Charger answered but the request failed (an HTTP error status,
            # malformed response, wrong firmware model, …) — this needs the
            # user's attention.
            #
            # No 401 branch on purpose: /main is a POST, and POST handlers on this
            # firmware check no credentials at all (KB-01 §1.2, live on V1
            # 2026-07-30 and V2 R3.05.4 2026-08-13). A ConfigEntryAuthFailed here
            # would have been unreachable code that, if it ever did fire, stops
            # polling for good — the core only reschedules when the failure was
            # not an auth failure. Credentials are validated in the config flow,
            # which probes the one handler that does check them.
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"device_error_{self._entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="device_error",
                translation_placeholders={"device_name": self._device_name},
            )
            raise UpdateFailed(f"Error updating: {exc}") from exc

    @callback
    def _write_sw_version_to_registry(self, data: dict[str, Any]) -> None:
        """Put the firmware version on the device page after an offline start.

        HA reads `device_info` exactly once, when an entity registers. Setup no
        longer waits for the charger to be reachable, so at registration time
        there is no version yet — and it would never appear until a reload that
        happens to catch the station online, which for a charger that comes up
        once a week is a long time.

        Not gated on "the first successful poll": on V1 the version arrives from
        a separate GET that _load_sw_version_once retries, so it can land on the
        second or third success.
        """
        if self._device_version_written:
            return
        version = firmware_version(data, self.charger)
        if not version:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self._entry_id)})
        if device is None:
            # Online start: this poll runs BEFORE async_forward_entry_setups, so
            # no device exists yet and device_info will carry the version anyway.
            # Deliberately not touching device.id here — an AttributeError inside
            # _async_update_data lands in the broad except below and turns a
            # healthy poll into a repair issue with every entity unavailable.
            # The flag stays down so a later poll can still do the write.
            return
        registry.async_update_device(device.id, sw_version=version)
        self._device_version_written = True

    async def _load_sw_version_once(self) -> None:
        """Fetch the firmware version on the first successful poll.

        Generations whose /main carries no version read it from the page the
        station serves (V1); a no-op elsewhere, and never fatal. This runs here
        rather than at setup because setup no longer waits for the charger to be
        reachable — at setup the request would only burn its timeout while the
        station is offline, and would never be retried once the entry loaded.
        """
        if self._sw_version_loaded:
            return
        await self.charger.async_load_sw_version()
        # The flag turns on the RESULT, not on "no exception was raised":
        # ChargerV1.async_load_sw_version swallows its own error and returns, so
        # a failed first attempt looks identical to a successful one from here.
        # Retry on later polls instead, bounded — this is a GET with a 10s
        # timeout inside the poll loop, and a generation that reports no version
        # at all must not be asked forever.
        if self.charger.sw_version is not None:
            self._sw_version_loaded = True
            return
        self._sw_version_attempts += 1
        if self._sw_version_attempts >= _SW_VERSION_MAX_ATTEMPTS:
            self._sw_version_loaded = True
            # Warn once, and only when a reason was actually recorded. Exhausting
            # the counter is not by itself a failure: the base implementation is a
            # no-op, so every V2 install runs it out and records nothing. Keying
            # off the counter alone would warn on every V2 start.
            if self.charger.sw_version_error:
                _LOGGER.warning(
                    "%s: could not read the firmware version after %d attempts (%s). "
                    "The device page will show no firmware.",
                    self.charger.ip,
                    self._sw_version_attempts,
                    self.charger.sw_version_error,
                )

    def _end_session(self, ended_state, base) -> None:
        """Publish the session that just ended and drop the live figures."""
        self.last_session = {
            "energy_kwh": self._live_energy,
            "duration_s": self._live_time,
            "ended_state": ended_state,
            "ended_at": dt_util.utcnow().isoformat(),
        }
        self.hass.bus.async_fire(EVENT_SESSION_ENDED, {**base, **self.last_session})
        self._live_energy = None
        self._live_time = None

    def _process_session_events(self, data) -> None:
        new_state = data.get("state")
        base = {"entry_id": self._entry_id, "device_name": self._device_name}
        latched_start = False

        if new_state in SESSION_ACTIVE_STATES:
            # The firmware wipes sessionEnergy/sessionTime the moment the next
            # session starts, so capture the last values seen while active —
            # they are the only reliable final figures for the ended session.
            # sessionEnergy is coerced here rather than compared raw: V2's
            # transform_data passes it through untouched, so a non-numeric value
            # would otherwise settle into _live_energy and make the comparison
            # below raise on the *next* poll — one bad field turning into
            # UpdateFailed for everything.
            se = as_float(data.get("sessionEnergy"))
            st = data.get("sessionTime")

            # A session counter back at exactly zero while the state is still
            # active is a session boundary the state machine never showed. It is
            # what a power cut looks like from here: the station boots straight
            # back into charging, so session_transition("charging", "charging")
            # is None and nothing latched — while the capture below would
            # overwrite the old figures with the new session's zero. Measured on
            # V2 2026-09-01: 12.901 kWh vanished this way.
            # Exactly zero, not "any drop": a reboot always restarts the counter
            # at zero, and a small rollback (observed on totalEnergy) never
            # reaches it — so the rule does not depend on whether the station can
            # decrease sessionEnergy mid-session. The `> 0` guard keeps a session
            # that was interrupted before its first tenth of a kWh from latching
            # a zero over a meaningful previous value.
            if se == 0 and self._live_energy is not None and self._live_energy > 0:
                self._end_session(new_state, base)
                self.hass.bus.async_fire(EVENT_CHARGING_STARTED, base)
                latched_start = True

            if se is not None:
                self._live_energy = se
            if st is not None:
                self._live_time = st

        if self._prev_state is not None:
            event = session_transition(self._prev_state, new_state)
            if event == "charging_started":
                # paused -> charging with a zeroed counter latches above AND
                # transitions here; firing twice would break the started/ended
                # pairing this very fix exists to keep.
                if not latched_start:
                    self.hass.bus.async_fire(EVENT_CHARGING_STARTED, base)
            elif event == "session_ended":
                self._end_session(new_state, base)

        self._prev_state = new_state
