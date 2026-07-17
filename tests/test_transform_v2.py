"""Unit tests for ChargerV2.transform_data."""

from datetime import UTC, datetime

from charger.v2 import ChargerV2


def _charger() -> ChargerV2:
    return ChargerV2("1.2.3.4")


def test_state_mapping():
    charger = _charger()
    assert charger.transform_data({"state": 4})["state"] == "charging"
    assert charger.transform_data({"state": 7})["state"] == "error"
    assert charger.transform_data({"state": 99})["state"] == "unknown"


def test_substate_uses_error_map_in_error_state():
    out = _charger().transform_data({"state": 7, "subState": 3})
    assert out["state"] == "error"
    assert out["subState"] == "relay_error"


def test_substate_uses_limit_map_otherwise():
    out = _charger().transform_data({"state": 4, "subState": 3})
    assert out["state"] == "charging"
    assert out["subState"] == "time_limit"


def test_substate_missing_and_unknown():
    charger = _charger()
    assert charger.transform_data({"state": 4})["subState"] == "unknown"
    assert charger.transform_data({"state": 4, "subState": 99})["subState"] == "unknown"


def test_ai_status_mapping():
    charger = _charger()
    assert charger.transform_data({"aiStatus": 2})["aiStatus"] == "tesla_auto"
    assert charger.transform_data({"aiStatus": 3})["aiStatus"] == "power"
    assert charger.transform_data({"aiStatus": 99})["aiStatus"] == "unknown"


def test_system_time_valid():
    out = _charger().transform_data({"systemTime": 1751884800})
    assert out["systemTime"] == datetime.fromtimestamp(1751884800, tz=UTC)
    assert out["systemTime"].tzinfo is UTC


def test_system_time_invalid():
    assert _charger().transform_data({"systemTime": "garbage"})["systemTime"] is None


def test_input_dict_not_mutated():
    raw = {"state": 7, "subState": 3}
    _charger().transform_data(raw)
    assert raw == {"state": 7, "subState": 3}
