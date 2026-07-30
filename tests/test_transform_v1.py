"""Unit tests for ChargerV1.transform_data."""

from datetime import datetime

from charger.v1 import ChargerV1


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
