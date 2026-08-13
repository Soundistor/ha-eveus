"""Binary sensor tests: debounce + firmware-fault bypass (current behavior).

Locks the debounce mechanics against regression. Ground/groundCtrl semantics
(Bug 1/2) confirmed live on 2026-07-27 (firmware R3.05.4/R3.05.5, "PE control
On" display matched groundCtrl 0->1) and fixed in binary_sensor.py.
"""
from __future__ import annotations

from custom_components.eveus.binary_sensor import (
    BINARY_SENSORS,
    DEBOUNCE_THRESHOLD,
    ChargerBinarySensor,
    EveusConnectivitySensor,
)
from custom_components.eveus.charger.v1 import V1_STATE_MAP
from custom_components.eveus.charger.v2 import V2_STATE_MAP, V2_SUBSTATE_ERROR_MAP
from custom_components.eveus.coordinator import FIRMWARE_FAULT_STATES

_DESC = {d.key: d for d in BINARY_SENSORS}
_ACTIVE = {"ground": 0, "groundCtrl": 1}   # raw value that means "on" per key
_INACTIVE = {"ground": 1, "groundCtrl": 0}  # raw value that means "off" per key


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
        key: _ACTIVE[key] if on else _INACTIVE[key],
        "state": state,
        "subState": substate,
    }
    sensor._handle_coordinator_update()


def test_debounce_requires_three_consecutive_on():
    """Only the SAFETY sensor is debounced."""
    key = "ground"
    sensor = _make(key)
    _feed(sensor, key, True)
    assert sensor.is_on is False          # 1
    _feed(sensor, key, True)
    assert sensor.is_on is False          # 2
    _feed(sensor, key, True)
    assert sensor.is_on is True           # 3 -> threshold
    assert DEBOUNCE_THRESHOLD == 3


def test_config_flag_is_not_debounced():
    """groundCtrl is stored configuration — it must follow the raw value at once."""
    key = "groundCtrl"
    sensor = _make(key)
    _feed(sensor, key, True)
    assert sensor.is_on is True
    _feed(sensor, key, False)
    assert sensor.is_on is False


def test_single_off_resets_debounce():
    key = "ground"
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
    _feed(sensor, "ground", True, state="no_ground")   # V1 firmware fault
    assert sensor.is_on is True                        # immediate, no 3-in-a-row


def test_grounding_error_bypasses_debounce():
    """The very fault the ground sensor represents used to be the slowest.

    grounding_error was missing from FIRMWARE_FAULT_STATES, so a ground fault
    took the full debounce — up to 3 polls, i.e. ~3 minutes.
    """
    sensor = _make("ground")
    _feed(sensor, "ground", True, state="error", substate="grounding_error")
    assert sensor.is_on is True


def test_fault_states_all_come_from_a_state_map():
    """Every member must be a value some map actually produces.

    cpu_error and relay_stuck sat in the set while no map emitted them — dead
    entries that read as coverage.
    """
    produced = (
        set(V1_STATE_MAP.values())
        | set(V2_STATE_MAP.values())
        | set(V2_SUBSTATE_ERROR_MAP.values())
    )
    assert produced >= FIRMWARE_FAULT_STATES


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
    _feed(sensor, "ground", False, state="no_ground")  # fault + raw off -> count 0
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
