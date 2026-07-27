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
    """No timeZone in the payload -> the epoch is taken as is."""
    out = _charger().transform_data({"systemTime": 1751884800})
    assert out["systemTime"] == datetime.fromtimestamp(1751884800, tz=UTC)
    assert out["systemTime"].tzinfo is UTC


def test_system_time_subtracts_the_station_offset():
    """systemTime is UTC + timeZone*3600, not an absolute epoch."""
    out = _charger().transform_data({"systemTime": 1751884800, "timeZone": 3})
    assert out["systemTime"] == datetime.fromtimestamp(1751884800 - 3 * 3600, tz=UTC)


def test_system_time_negative_offset():
    out = _charger().transform_data({"systemTime": 1751884800, "timeZone": -5})
    assert out["systemTime"] == datetime.fromtimestamp(1751884800 + 5 * 3600, tz=UTC)


def test_system_time_invalid():
    assert _charger().transform_data({"systemTime": "garbage"})["systemTime"] is None


def test_system_time_invalid_timezone():
    """A garbage timeZone must not take the whole transform down."""
    out = _charger().transform_data(
        {"state": 4, "systemTime": 1751884800, "timeZone": "x"}
    )
    assert out["systemTime"] is None
    assert out["state"] == "charging"


def test_time_msg_invalidates_system_time():
    """timeMsg == 1 means the station's clock is unusable."""
    payload = {
        "state": 4,
        "subState": 3,
        "aiStatus": 2,
        "systemTime": 1751884800,
        "timeZone": 3,
    }
    healthy = _charger().transform_data({**payload, "timeMsg": 0})
    invalid = _charger().transform_data({**payload, "timeMsg": 1})

    assert invalid["systemTime"] is None
    assert healthy["systemTime"] == datetime.fromtimestamp(1751884800 - 3 * 3600, tz=UTC)
    # Every other field is identical to the healthy case.
    assert {k: v for k, v in invalid.items() if k not in ("systemTime", "timeMsg")} == {
        k: v for k, v in healthy.items() if k not in ("systemTime", "timeMsg")
    }


def test_time_msg_zero_keeps_system_time():
    out = _charger().transform_data({"systemTime": 1751884800, "timeMsg": 0})
    assert out["systemTime"] == datetime.fromtimestamp(1751884800, tz=UTC)


def test_input_dict_not_mutated():
    raw = {"state": 7, "subState": 3}
    _charger().transform_data(raw)
    assert raw == {"state": 7, "subState": 3}
