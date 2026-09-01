"""What a fabricated 0.0 did downstream on V1.

The guard itself is unit-tested in test_transform_v1.py. These two go one layer
up, because the guard is only worth having for what the zero caused: a false
last_reset on the session graph and a poisoned daily baseline. They feed the
coordinator THROUGH ChargerV1.transform_data on purpose — test_daily_sensors.py
builds the coordinator dict by hand and cannot see this class of bug at all.
"""
from __future__ import annotations

from datetime import datetime

from charger.v1 import ChargerV1
from homeassistant.util import dt as dt_util
import pytest

import custom_components.eveus.sensor as sensor_mod
from custom_components.eveus.sensor import (
    _SESSION_ENERGY_DESCRIPTION,
    DailyEnergySensor,
    SessionEnergySensor,
)

_DAY = datetime(2026, 7, 1, 12, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)


class _Coord:
    def __init__(self):
        self.data: dict = {}
        self.last_update_success = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


class _Charger:
    ip = "1.2.3.4"
    model_name = "V1"
    capabilities: set = set()


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(sensor_mod.dt_util, "now", lambda: _DAY)


def _feed(entity, coord, raw: dict) -> None:
    """Drive one poll the way the coordinator does — through transform_data."""
    coord.data = ChargerV1("1.2.3.4").transform_data(raw)
    entity._handle_coordinator_update()


def test_a_frame_without_session_energy_does_not_fake_a_reset():
    coord = _Coord()
    sensor = SessionEnergySensor(coord, _Charger(), _SESSION_ENERGY_DESCRIPTION, "smoke", "e1")
    sensor.async_write_ha_state = lambda: None

    _feed(sensor, coord, {"sessionEnergy": 123})       # 12.3 kWh
    assert sensor._prev_energy == 12.3

    _feed(sensor, coord, {"sessionEnergy": None})      # garbage, not a new session
    assert sensor._attr_last_reset is None, (
        "a coerced 0.0 read as 'the counter restarted' and stamped last_reset, "
        "which corrupts long-term statistics rather than just the graph"
    )


def test_a_frame_without_total_energy_does_not_move_the_daily_baseline():
    coord = _Coord()
    sensor = DailyEnergySensor(coord, _Charger(), "smoke", "e1")
    sensor.async_write_ha_state = lambda: None

    _feed(sensor, coord, {"totalEnergy": 2500})        # 250.0 kWh -> baseline
    _feed(sensor, coord, {"totalEnergy": 2730})        # 273.0 kWh
    assert sensor.native_value == 23.0

    _feed(sensor, coord, {"totalEnergy": ""})          # garbage
    assert sensor._baseline == 250.0, (
        "a coerced 0.0 crossed the baseline, rebased it negative, and the next "
        "healthy frame jumped the day up by roughly the lifetime total"
    )
    assert sensor.native_value == 23.0, "the day holds through a bad frame"

    _feed(sensor, coord, {"totalEnergy": 2735})
    assert sensor.native_value == 23.5
