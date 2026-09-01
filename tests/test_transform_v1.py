"""Unit tests for ChargerV1.transform_data."""

from datetime import datetime
import logging

from charger.v1 import ChargerV1
import pytest


def _charger() -> ChargerV1:
    return ChargerV1("1.2.3.4")


def test_scaling_and_power():
    raw = {
        "voltMeas1": 230,
        "curMeas1": 160,  # 0.1 A units -> 16.0 A
        "sessionEnergy": 123,  # 0.1 kWh units -> 12.3
        "totalEnergy": 4567,  # -> 456.7
        "state": 3,
        "aiStatus": 1,
    }
    out = _charger().transform_data(raw)
    # powerMeas = V * raw_I * 0.1, computed BEFORE curMeas1 is scaled
    assert out["powerMeas"] == 3680.0
    assert out["curMeas1"] == 16.0
    assert out["sessionEnergy"] == 12.3
    assert out["totalEnergy"] == 456.7


def test_state_mapping():
    """The station's own enum — every code it can report.

    Measured live on EnergyStar V5.23 (2026-07-30): unplugged -> 12, a plugged
    car that is not charging -> 9.
    """
    charger = _charger()
    for num, expected in (
        (0, "no_data"), (6, "charging"), (9, "waiting"), (12, "ready"),
        (13, "delayed_start"), (14, "overcurrent"), (15, "overvoltage"),
        (16, "current_leak"), (17, "station_error"), (18, "overheat"),
        (19, "locked"), (20, "no_ground"), (21, "overheat_plug"),
        (22, "undervoltage"),
    ):
        assert charger.transform_data({"state": num})["state"] == expected
    assert charger.transform_data({"state": 99})["state"] == "unknown"
    # Missing state defaults to 0 -> no_data
    assert charger.transform_data({})["state"] == "no_data"


def test_measured_states_are_not_faults():
    """The two states the old map turned into invented faults."""
    charger = _charger()
    # plugged in, not charging — used to read "no_ground"
    assert charger.transform_data({"state": 9})["state"] == "waiting"
    # unplugged — used to read "overcurrent"
    assert charger.transform_data({"state": 12})["state"] == "ready"


def test_codes_absent_from_the_station_enum_are_unknown():
    """1..5, 7, 8, 10, 11 do not exist on V1 — never guess a meaning for them."""
    charger = _charger()
    for num in (1, 2, 3, 4, 5, 7, 8, 10, 11):
        assert charger.transform_data({"state": num})["state"] == "unknown"


def test_ai_status_mapping():
    charger = _charger()
    assert charger.transform_data({"aiStatus": 0})["aiStatus"] == "off"
    assert charger.transform_data({"aiStatus": 1})["aiStatus"] == "voltage"
    assert charger.transform_data({"aiStatus": 99})["aiStatus"] == "unknown"


def test_system_time_valid():
    out = _charger().transform_data({"systemTime": "12:34:56"})
    ts = out["systemTime"]
    assert isinstance(ts, datetime)
    # Naive wall-clock time-of-day: the coordinator localizes it to HA's tz.
    assert ts.tzinfo is None
    assert (ts.hour, ts.minute, ts.second) == (12, 34, 56)
    assert ts.date() == datetime.now().date()


def test_system_time_invalid():
    assert _charger().transform_data({"systemTime": "garbage"})["systemTime"] is None


def test_system_time_missing():
    assert "systemTime" not in _charger().transform_data({"state": 1})


def test_input_dict_not_mutated():
    raw = {"curMeas1": 160, "state": 3}
    _charger().transform_data(raw)
    assert raw == {"curMeas1": 160, "state": 3}


def test_absent_temperature_sentinel():
    """Below -50 means "no sensor", not a reading."""
    out = _charger().transform_data({"temperature1": 34, "temperature2": -60})
    assert out["temperature1"] == 34
    assert out["temperature2"] is None


def test_temperature_missing_key_is_not_created():
    assert "temperature1" not in _charger().transform_data({"state": 1})


def test_adaptive_current_is_hidden_while_adaptive_mode_is_off():
    """aiModecurrent keeps a stale figure with the mode off — report nothing."""
    from custom_components.eveus.sensor import (
        _ADAPTIVE_CURRENT_DESCRIPTION,
        AdaptiveCurrentSensor,
    )

    class _Coord:
        def __init__(self, data):
            self.data = data
            self.last_update_success = True

        def async_add_listener(self, update_callback, context=None):
            return lambda: None

    class _Ch:
        ip = "1.2.3.4"
        model_name = "V1"
        sw_version = None

    def _value(data):
        sensor = AdaptiveCurrentSensor(
            _Coord(data), _Ch(), _ADAPTIVE_CURRENT_DESCRIPTION, "smoke", "e1"
        )
        return sensor.native_value

    assert _value({"aiStatus": "voltage", "aiModecurrent": 7}) == 7
    assert _value({"aiStatus": "off", "aiModecurrent": 6}) is None
    assert _value({"aiModecurrent": 6}) is None


@pytest.mark.parametrize("garbage", [None, "", "abc", [], {}, float("nan")])
def test_unparseable_enum_codes_fold_to_unknown(garbage):
    """Same hardening as V2: garbage in an enum field must not kill the poll."""
    out = _charger().transform_data({"state": garbage, "aiStatus": garbage})
    assert out["state"] == "unknown"
    assert out["aiStatus"] == "unknown"


# --------------------------------------------------------------------------- #
# Numeric fields: same hardening the enum fields already had (as_enum_int)
# --------------------------------------------------------------------------- #

_NUMERIC = ("voltMeas1", "curMeas1", "sessionEnergy", "totalEnergy")


@pytest.mark.parametrize("garbage", [None, "", "abc", [], {}, float("nan")])
@pytest.mark.parametrize("key", _NUMERIC)
def test_unparseable_numeric_field_drops_the_key(key, garbage):
    """Never 0.0, never an exception — the key is simply not written.

    0.0 is the dangerous answer, not the missing key: it passes every
    `is not None` guard downstream (last_reset, the daily baseline,
    _live_energy) and the sensor reports a confident zero.
    """
    out = _charger().transform_data({key: garbage})
    assert key not in out
    assert "powerMeas" not in out


def test_absent_numeric_fields_are_not_invented():
    out = _charger().transform_data({"state": 6})
    for key in (*_NUMERIC, "powerMeas"):
        assert key not in out


def test_power_is_derived_only_when_both_factors_are_real():
    out = _charger().transform_data({"voltMeas1": 230})
    assert "powerMeas" not in out
    assert out["voltMeas1"] == 230, "a good field must survive a bad neighbour"


def test_numeric_strings_parse():
    """The station sends ints today; a numeric string is still a number."""
    out = _charger().transform_data({"voltMeas1": "230", "curMeas1": "160"})
    assert out["curMeas1"] == 16.0
    assert out["powerMeas"] == 3680.0


def test_garbage_is_named_once_per_charger_not_once_per_poll(caplog):
    charger = _charger()
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            charger.transform_data({"voltMeas1": None, "totalEnergy": "abc"})
    lines = [r.getMessage() for r in caplog.records if "unparseable numeric" in r.getMessage()]
    assert len(lines) == 1, "a 30 s poll must not repeat this line forever"
    assert "voltMeas1" in lines[0] and "totalEnergy" in lines[0]


def test_an_absent_key_is_not_reported_as_garbage(caplog):
    with caplog.at_level(logging.WARNING):
        _charger().transform_data({"state": 6})
    assert not [r for r in caplog.records if "unparseable numeric" in r.getMessage()]
