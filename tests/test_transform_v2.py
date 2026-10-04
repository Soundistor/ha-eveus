"""Unit tests for ChargerV2.transform_data."""

from datetime import UTC, datetime
import logging

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
    """The garbage half flipped: a non-numeric reading is now REMOVED.

    It used to be left in the frame on the grounds that it "never raises" in
    transform_data. It does raise later: Home Assistant rejects a non-numeric
    state for an entity with a numeric device class, and the coordinator runs
    its listeners in a bare loop, so the frame's remaining entities never get
    updated.
    """
    out = _charger().transform_data({"temperature1": -50, "temperature2": "x"})
    assert out["temperature1"] == -50    # exactly -50 is still a reading
    assert "temperature2" not in out


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


# Every shape json.loads or the station can put where a number belongs.
# "nan" and "inf" as STRINGS matter as much as the bare tokens: Home Assistant
# parses a string state into a float before checking isfinite, so a quoted one
# reaches the same ValueError — and C encoders are far likelier to emit that
# than a bare NaN token.
_GARBAGE = ["", "abc", [], {}, float("nan"), float("inf"), float("-inf"), "nan", "inf"]


@pytest.mark.parametrize("field", ChargerV2.numeric_fields)
@pytest.mark.parametrize("garbage", _GARBAGE)
def test_no_numeric_field_carries_garbage_out_of_transform(field, garbage):
    """The whole closed list, against everything that is not a number.

    Parametrised over the real tuple rather than a copy, so adding a field to
    the charger adds it here. A field left uncoerced shows up as its own rows
    failing and nothing else — which is what makes this worth running as a
    mutation check.
    """
    out = _charger().transform_data({field: garbage})

    # Absent or explicitly None — both read as unknown through .get, and both
    # are safe. What must never happen is the value itself surviving: the
    # temperatures take the second route, because anything below -50 is the
    # firmware's "sensor absent" sentinel and -inf lands there first.
    assert out.get(field) is None, f"{field}={garbage!r} reached the frame"


@pytest.mark.parametrize("field", ChargerV2.numeric_fields)
def test_a_real_number_is_left_exactly_as_it_arrived(field):
    """Validation, not conversion.

    Replacing the value with the parsed float would turn every integer field
    into a float, and HA renders a float state through a float format — so
    recorded states would go from "30" to "30.0" and string comparisons in
    user templates would quietly change meaning.
    """
    out = _charger().transform_data({field: 30})

    assert out[field] == 30
    assert isinstance(out[field], int), "an int must not become a float"


def test_garbage_is_named_once_per_charger_not_once_per_poll(caplog):
    charger = _charger()
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            charger.transform_data({"totalEnergy": "abc"})

    lines = [r for r in caplog.records if "unparseable numeric field" in r.message]
    assert len(lines) == 1, "a station gone bad would fill the log forever"
    assert "totalEnergy" in lines[0].getMessage()


def test_two_chargers_warn_independently(caplog):
    """The flag is a class-level default, written through self.

    One station going bad must not silence the other. Sharing a single flag is
    the natural misreading of "the two generations do not keep two copies".
    """
    first, second = ChargerV2("1.2.3.4"), ChargerV2("5.6.7.8")
    with caplog.at_level(logging.WARNING):
        first.transform_data({"totalEnergy": "abc"})
        second.transform_data({"totalEnergy": "abc"})

    lines = [r for r in caplog.records if "unparseable numeric field" in r.message]
    assert len(lines) == 2
    assert {"1.2.3.4", "5.6.7.8"} == {line.getMessage().split(":")[0] for line in lines}


def test_the_coerced_field_list_is_pinned():
    """The sweep above parametrises over the tuple, so it cannot police it.

    Delete a field from numeric_fields and that field's rows simply stop
    existing — the suite shrinks and stays green. Caught by mutation: removing
    currentSet took the count from 682 to 672 with nothing red. So the list
    itself is pinned here, and the exclusions are named rather than implied.
    """
    assert set(ChargerV2.numeric_fields) == {
        "currentSet", "curDesign", "curMeas1", "voltMeas1", "powerMeas",
        "temperature1", "temperature2", "aiVoltage", "aiModecurrent",
        "sessionTime", "sessionEnergy", "totalEnergy", "leakValue",
        "vBat", "RSSI", "IEM1", "IEM2", "minCurrent",
    }

    numeric_in_capabilities = {
        "currentSet", "curDesign", "curMeas1", "voltMeas1", "powerMeas",
        "temperature1", "temperature2", "aiVoltage", "aiModecurrent",
        "sessionTime", "sessionEnergy", "totalEnergy", "leakValue",
        "vBat", "RSSI", "IEM1", "IEM2",
        # Deliberately NOT coerced, each for its own reason:
        "state", "subState", "aiStatus",   # mapped to strings before anyone reads them
        "systemTime",                      # own handling; dropping breaks the absent-clock contract
        "evseEnabled", "ground", "groundCtrl",   # 0/1 flags compared as ints
    }
    assert numeric_in_capabilities <= _charger().capabilities | {"minCurrent"}, (
        "a capability was renamed without this list being revisited"
    )


@pytest.mark.parametrize(
    "frame",
    [
        {"systemTime": 1751884800, "timeZone": float("inf")},
        {"systemTime": float("inf"), "timeZone": 2},
        {"systemTime": 10 ** 30, "timeZone": 2},
        {"systemTime": float("nan"), "timeZone": 2},
        {"systemTime": [], "timeZone": 2},
        {"systemTime": "", "timeZone": 2},
        {"systemTime": {}, "timeZone": 2},
    ],
)
def test_a_poisoned_clock_does_not_fail_the_whole_poll(frame):
    """These two fields are excluded from coercion — so they must cope alone.

    The exclusion was justified by "they handle their own garbage", which held
    for NaN (int() raises ValueError, already caught) and not for Infinity:
    int(inf) raises OverflowError, which escaped transform_data entirely. The
    coordinator then reports UpdateFailed and EVERY entity goes unavailable
    for as long as the station keeps sending it — worse than the single stale
    sensor this whole file exists to prevent.
    """
    out = _charger().transform_data(frame)

    assert out["systemTime"] is None
