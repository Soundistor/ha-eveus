"""A lifetime counter that stepped backwards, and what the day made of it.

These drive a real ChargerCoordinator and hand its output to a real
DailyEnergySensor. That wiring is the point: the guard lives in the
coordinator, so a test that builds the coordinator dict by hand — as
test_daily_sensors.py does — cannot see it at all and would still show the old
numbers.

Two measured inputs, same shape, different mechanism:
  * 119.8 -> 0 -> 119.8, the counter not loaded from flash yet (V1, 2026-09-10);
  * 78.5 -> 77.9, a tail the station never flushed and never gets back
    (V1, 2026-09-03).
The first must be refused, the second believed once it repeats — otherwise the
sensor freezes until the counter climbs back past its old maximum.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.util import dt as dt_util
import pytest

from custom_components.eveus.coordinator import WRITE_SETTLE, ChargerCoordinator
import custom_components.eveus.sensor as sensor_mod
from custom_components.eveus.sensor import DailyEnergySensor

_DAY = datetime(2026, 9, 13, 12, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)


class _Charger:
    ip = "1.2.3.4"
    model_name = "V1"
    capabilities: set = set()
    min_current = 7
    sw_version: str | None = "EnergyStar V5.23"
    sw_version_error: str | None = None

    def __init__(self):
        self._data: dict = {}

    def set_data(self, data: dict) -> None:
        self._data = data

    async def get_status(self):
        return dict(self._data)

    async def async_load_sw_version(self) -> None:
        return None

    def transform_data(self, raw):
        return raw


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    """Local date the daily sensor sees. Mutable so a test can cross midnight."""
    box = [_DAY]
    monkeypatch.setattr(sensor_mod.dt_util, "now", lambda: box[0])
    return box


def _coordinator(hass) -> ChargerCoordinator:
    return ChargerCoordinator(hass, _Charger(), "e1", "Eveus Test")


def _daily(coord) -> DailyEnergySensor:
    sensor = DailyEnergySensor(coord, coord.charger, "smoke", "e1")
    sensor.async_write_ha_state = lambda: None
    return sensor


async def _poll(coord, sensor=None, **data):
    """One full poll: through the coordinator, then into the entity."""
    coord.charger.set_data(data)
    coord.data = await coord._async_update_data()
    if sensor is not None:
        sensor._handle_coordinator_update()
    return coord.data


async def test_a_reboot_zero_never_reaches_the_day(hass):
    coord = _coordinator(hass)
    sensor = _daily(coord)

    await _poll(coord, sensor, totalEnergy=119.8)          # baseline for the day
    await _poll(coord, sensor, totalEnergy=119.9)
    held = await _poll(coord, sensor, totalEnergy=0)       # the reboot frame
    await _poll(coord, sensor, totalEnergy=120.0)

    assert "totalEnergy" not in held
    # Without the guard the zero rebases the baseline to 0 and the day starts
    # reporting the whole lifetime counter: 134 kWh in a day on a 4.2 kW
    # station, measured 2026-09-10.
    assert sensor.native_value == 0.2


async def test_a_small_rollback_adds_no_energy_that_never_happened(hass):
    coord = _coordinator(hass)
    sensor = _daily(coord)

    await _poll(coord, sensor, totalEnergy=100.0)          # baseline
    await _poll(coord, sensor, totalEnergy=100.2)
    await _poll(coord, sensor, totalEnergy=99.9)           # dips under baseline
    await _poll(coord, sensor, totalEnergy=100.4)

    # The day really gained 0.4. The old rebase branch kept the 0.3 dip as well
    # and reported 0.7.
    assert sensor.native_value == 0.4


async def test_a_counter_that_stays_low_is_believed(hass, freezer):
    coord = _coordinator(hass)

    await _poll(coord, totalEnergy=119.8)
    await _poll(coord, totalEnergy=0)                      # held back
    freezer.tick(coord.update_interval)
    second = await _poll(coord, totalEnergy=0)             # confirmed

    # A real reset, or a tail the station is never getting back. Refusing it
    # forever would freeze the sensor until the counter climbed past 119.8.
    assert second["totalEnergy"] == 0
    assert coord._counter_dropped == 1


async def test_two_frames_three_seconds_apart_do_not_confirm(hass, freezer):
    coord = _coordinator(hass)

    await _poll(coord, totalEnergy=119.8)
    await _poll(coord, totalEnergy=0)
    freezer.tick(WRITE_SETTLE)                             # a write-triggered poll
    still_held = await _poll(coord, totalEnergy=0)

    # Every write to number/switch/select schedules a poll WRITE_SETTLE later,
    # and Force Refresh fires one immediately. Counting frames alone let two
    # reads 3 s apart confirm a zero, while the station's boot window is far
    # longer than that — so the guard would rebase on exactly the reading it
    # exists to refuse. Confirmation has to span a real poll interval.
    assert "totalEnergy" not in still_held


async def test_a_permanent_loss_costs_exactly_one_frame(hass, freezer):
    coord = _coordinator(hass)

    await _poll(coord, totalEnergy=78.5)
    await _poll(coord, totalEnergy=77.9)                   # held back
    freezer.tick(coord.update_interval)
    resumed = await _poll(coord, totalEnergy=78.0)         # still low -> believed

    assert resumed["totalEnergy"] == 78.0


async def test_the_day_rolls_over_only_on_a_frame_with_a_reading(hass, _clock):
    coord = _coordinator(hass)
    sensor = _daily(coord)

    await _poll(coord, sensor, totalEnergy=100.0)          # baseline, day N
    await _poll(coord, sensor, totalEnergy=100.5)          # day N gained 0.5

    _clock[0] = _DAY + timedelta(days=1)
    await _poll(coord, sensor, totalEnergy=0)              # held back, crosses midnight
    await _poll(coord, sensor, totalEnergy=100.6)          # first real frame of day N+1

    # Rolling over on a frame with no reading left _baseline None while
    # _computed still held yesterday's 0.5, and the rebase branch then set
    # baseline = total - 0.5 — so the new day opened already holding 0.5.
    assert sensor.native_value == 0.0


async def test_session_energy_is_not_guarded(hass):
    coord = _coordinator(hass)

    await _poll(coord, state="charging", sessionEnergy=12.9)
    frame = await _poll(coord, state="charging", sessionEnergy=0)

    # It falls to zero at the start of every session, and the power-cut latch
    # in _process_session_events is built on exactly that zero (its own tests
    # live in test_session_power_loss.py). Guarding it would break both.
    assert frame["sessionEnergy"] == 0
    assert coord._counter_dropped == 0


@pytest.mark.parametrize("key", ["IEM1", "IEM2"])
async def test_the_trip_meters_are_guarded_too(hass, key):
    coord = _coordinator(hass)

    await _poll(coord, **{key: 4126.8})
    held = await _poll(coord, **{key: 0})

    assert key not in held


async def test_holding_back_leaves_a_warning(hass, caplog):
    coord = _coordinator(hass)

    await _poll(coord, totalEnergy=119.8)
    with caplog.at_level(logging.WARNING):
        await _poll(coord, totalEnergy=0)

    # A frame we refused is invisible in the entity, which just reads unknown.
    assert "totalEnergy" in caplog.text


async def test_the_first_frame_after_a_restart_is_believed(hass):
    coord = _coordinator(hass)

    frame = await _poll(coord, totalEnergy=12.0)

    # RAM-only memory, stated in the coordinator: with nothing to compare
    # against, the first frame is taken as read. The gap this leaves — a
    # blackout that takes the station and HA together — is known and accepted.
    assert frame["totalEnergy"] == 12.0
    assert coord._counter_dropped == 0
