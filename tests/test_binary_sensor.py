"""Binary sensor tests: debounce + firmware-fault bypass (current behavior).

Locks the debounce mechanics against regression. SCOPE: tests behavior AS
WRITTEN — the ground/groundCtrl inversion fix (Bug 1/2) is Phase 4, blocked on
a live device, and will bring its own semantics tests. No production change.
"""
from __future__ import annotations

import pytest

from custom_components.eveus.binary_sensor import (
    BINARY_SENSORS,
    DEBOUNCE_THRESHOLD,
    ChargerBinarySensor,
    EveusConnectivitySensor,
)

_DESC = {d.key: d for d in BINARY_SENSORS}
_ACTIVE = {"ground": 1, "groundCtrl": 2}   # raw value that means "on" per key


class _Coord:
    def __init__(self):
        self.data: dict = {}
        self.last_update_success = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


class _Charger:
    ip = "1.2.3.4"
    model_name = "Test"
    capabilities: set = set()


def _make(key):
    sensor = ChargerBinarySensor(_Coord(), _Charger(), _DESC[key], "smoke", "e1")
    sensor.async_write_ha_state = lambda: None
    return sensor


def _feed(sensor, key, on, *, state="charging", substate=""):
    sensor.coordinator.data = {
        key: _ACTIVE[key] if on else 0,
        "state": state,
        "subState": substate,
    }
    sensor._handle_coordinator_update()


@pytest.mark.parametrize("key", ["ground", "groundCtrl"])
def test_debounce_requires_three_consecutive_on(key):
    sensor = _make(key)
    _feed(sensor, key, True)
    assert sensor.is_on is False          # 1
    _feed(sensor, key, True)
    assert sensor.is_on is False          # 2
    _feed(sensor, key, True)
    assert sensor.is_on is True           # 3 -> threshold
    assert DEBOUNCE_THRESHOLD == 3


@pytest.mark.parametrize("key", ["ground", "groundCtrl"])
def test_single_off_resets_debounce(key):
    sensor = _make(key)
    _feed(sensor, key, True)
    _feed(sensor, key, True)
    _feed(sensor, key, False)             # reset
    assert sensor.is_on is False
    _feed(sensor, key, True)
    _feed(sensor, key, True)
    assert sensor.is_on is False          # only 2 in a row again
    _feed(sensor, key, True)
    assert sensor.is_on is True


def test_firmware_fault_bypasses_debounce_via_state():
    sensor = _make("ground")
    _feed(sensor, "ground", True, state="cpu_error")   # firmware fault
    assert sensor.is_on is True                        # immediate, no 3-in-a-row


def test_firmware_fault_bypasses_debounce_via_substate():
    sensor = _make("ground")
    _feed(sensor, "ground", True, state="charging", substate="relay_error")
    assert sensor.is_on is True


def test_firmware_fault_off_clears_immediately():
    sensor = _make("ground")
    _feed(sensor, "ground", True)
    _feed(sensor, "ground", True)
    _feed(sensor, "ground", True)
    assert sensor.is_on is True
    _feed(sensor, "ground", False, state="cpu_error")  # fault + raw off -> count 0
    assert sensor.is_on is False


def _make_connectivity():
    sensor = EveusConnectivitySensor(_Coord(), _Charger(), "smoke", "e1")
    sensor.async_write_ha_state = lambda: None
    return sensor


def test_connectivity_tracks_last_update_success():
    sensor = _make_connectivity()
    sensor.coordinator.last_update_success = True
    assert sensor.is_on is True
    sensor.coordinator.last_update_success = False
    assert sensor.is_on is False


def test_connectivity_available_even_when_offline():
    sensor = _make_connectivity()
    sensor.coordinator.last_update_success = False
    assert sensor.available is True   # reports "disconnected", never unavailable
