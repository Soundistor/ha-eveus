"""Unit tests for ChargerV2.transform_data."""

from datetime import UTC, datetime

from charger.v2 import (
    AI_MODE_MAP,
    V2_STATE_MAP,
    V2_SUBSTATE_ERROR_MAP,
    V2_SUBSTATE_LIMIT_MAP,
    ChargerV2,
)
import pytest


def _charger() -> ChargerV2:
    return ChargerV2("1.2.3.4")


def test_state_mapping():
    charger = _charger()
    assert charger.transform_data({"state": 4})["state"] == "charging"
    assert charger.transform_data({"state": 7})["state"] == "error"
    assert charger.transform_data({"state": 99})["state"] == "unknown"


@pytest.mark.parametrize("code", sorted(V2_SUBSTATE_ERROR_MAP))
def test_substate_uses_error_map_in_error_state(code):
    out = _charger().transform_data({"state": 7, "subState": code})
    assert out["state"] == "error"
    assert out["subState"] == V2_SUBSTATE_ERROR_MAP[code]


@pytest.mark.parametrize("code", sorted(V2_SUBSTATE_LIMIT_MAP))
def test_substate_uses_limit_map_otherwise(code):
    out = _charger().transform_data({"state": 4, "subState": code})
    assert out["state"] == "charging"
    assert out["subState"] == V2_SUBSTATE_LIMIT_MAP[code]


@pytest.mark.parametrize("code", sorted(V2_STATE_MAP))
def test_every_state_code_maps(code):
    assert _charger().transform_data({"state": code})["state"] == V2_STATE_MAP[code]


@pytest.mark.parametrize("code", sorted(AI_MODE_MAP))
def test_every_ai_status_code_maps(code):
    assert _charger().transform_data({"aiStatus": code})["aiStatus"] == AI_MODE_MAP[code]


def test_contract_codes_are_pinned():
    """Literal values for the codes that carry an outside contract.

    The parametrized tests above read the same map the code does, so they prove
    the transform path but cannot catch two values being swapped inside a map.
    These can. Deliberately not the whole map: a literal copy of all 34 entries
    would have to be edited on every legitimate addition.
    """
    assert V2_SUBSTATE_LIMIT_MAP[9] == "external_limit"
    # Live-verified 2026-08-13: writing evseEnabled=1 on R3.05.4 put subState at
    # 1 and clearing it put it back to 0 (KB-03 R-0d).
    assert V2_SUBSTATE_LIMIT_MAP[1] == "limited_by_user"
    assert V2_SUBSTATE_LIMIT_MAP[0] == "no_limits"
    assert V2_SUBSTATE_ERROR_MAP[3] == "relay_error"
    assert V2_STATE_MAP[4] == "charging"
    assert V2_STATE_MAP[5] == "charge_complete"


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


def test_absent_temperature_sentinel():
    """Below -50 means "no sensor", not a reading."""
    out = _charger().transform_data({"temperature1": 34, "temperature2": -60})
    assert out["temperature1"] == 34
    assert out["temperature2"] is None


def test_temperature_boundary_and_garbage():
    out = _charger().transform_data({"temperature1": -50, "temperature2": "x"})
    assert out["temperature1"] == -50    # exactly -50 is still a reading
    assert out["temperature2"] == "x"    # non-numeric left alone, never raises


@pytest.mark.parametrize("garbage", [None, "", "abc", [], {}, float("nan")])
def test_unparseable_enum_codes_fold_to_unknown(garbage):
    """Non-numeric garbage used to escape transform_data entirely.

    A numeric-but-unmapped code already folded to "unknown" via the maps'
    .get() fallback; garbage raised out of here, was caught by the coordinator's
    broad except and became a repair issue for the whole poll.
    """
    out = _charger().transform_data(
        {"state": garbage, "subState": garbage, "aiStatus": garbage}
    )
    assert out["state"] == "unknown"
    assert out["subState"] == "unknown"
    assert out["aiStatus"] == "unknown"


def test_unreadable_state_does_not_pick_the_limit_map():
    """An unknown state must not make subState read as a charging limit.

    subState 1 means "limited_by_user" in the limit map. Without a readable
    state we cannot know which map applies, so the only honest answer is
    unknown — silently defaulting to the limit map would invent a reason.
    """
    out = _charger().transform_data({"state": "abc", "subState": 1})
    assert out["state"] == "unknown"
    assert out["subState"] == "unknown"


def test_json_null_state_is_a_typeerror_not_a_valueerror():
    """raw.get("state", 0) returns None when the key is present as JSON null.

    int(None) raises TypeError, so an except clause listing only ValueError
    would miss the most reachable kind of garbage.
    """
    out = _charger().transform_data({"state": None})
    assert out["state"] == "unknown"


@pytest.mark.parametrize("garbage", [None, "", "abc", [], {}, float("nan")])
def test_unparseable_time_msg_does_not_kill_the_poll(garbage):
    """The clock flag was the one bare int() left in V2.

    Garbage is not the "clock invalid" signal, so systemTime is decoded as
    usual — the flag simply does not fire, exactly as timeMsg=0 does not.
    """
    out = _charger().transform_data({"systemTime": 1751884800, "timeMsg": garbage})
    assert out["systemTime"] is not None
