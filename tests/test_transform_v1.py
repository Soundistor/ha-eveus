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
    charger = _charger()
    for num, expected in ((3, "charging"), (4, "charging"), (5, "charging"),
                          (6, "charging"), (8, "cpu_error"), (21, "relay_stuck")):
        assert charger.transform_data({"state": num})["state"] == expected
    assert charger.transform_data({"state": 99})["state"] == "unknown"
    # Missing state defaults to 0 -> no_data
    assert charger.transform_data({})["state"] == "no_data"


def test_ai_status_mapping():
    charger = _charger()
    assert charger.transform_data({"aiStatus": 0})["aiStatus"] == "off"
    assert charger.transform_data({"aiStatus": 1})["aiStatus"] == "voltage"
    assert charger.transform_data({"aiStatus": 99})["aiStatus"] == "unknown"


def test_system_time_valid():
    out = _charger().transform_data({"systemTime": "12:34:56"})
    ts = out["systemTime"]
    assert isinstance(ts, datetime)
    assert ts.tzinfo is not None
    assert (ts.hour, ts.minute, ts.second) == (12, 34, 56)
    assert ts.date() == datetime.now().astimezone().date()


def test_system_time_invalid():
    assert _charger().transform_data({"systemTime": "garbage"})["systemTime"] is None


def test_system_time_missing():
    assert "systemTime" not in _charger().transform_data({"state": 1})


def test_input_dict_not_mutated():
    raw = {"curMeas1": 160, "state": 3}
    _charger().transform_data(raw)
    assert raw == {"curMeas1": 160, "state": 3}
