"""One sensor answering "why is the charge not running, or not at my current".

subState first, state second. Reading state first is what the first design did,
and it was backwards: subState is meaningful under ANY state, and only
state == 7 switches which table it indexes (KB-02 §2.1). The single live frame
with a non-zero subState, measured 2026-09-01, proves it — a command stop gave
subState 1 (limited_by_user) together with state 5 (charge_complete), so a
state-first rule answers "Charge Complete" right after the user pressed stop.

Every test here is a criterion from the backlog item, including the mechanical
ones that exist to catch drift rather than to describe behaviour.
"""
from __future__ import annotations

import json
from pathlib import Path

from charger.v2 import V2_STATE_MAP, V2_SUBSTATE_LIMIT_MAP
import pytest

from custom_components.eveus.sensor import (
    _CHARGE_REASON_DESCRIPTION,
    _CHARGE_REASON_OPTIONS,
    _STATE_FALLBACK,
    ChargeReasonSensor,
)

_I18N = Path(__file__).resolve().parents[1] / "custom_components" / "eveus"
_FILES = [
    _I18N / "strings.json",
    _I18N / "translations" / "en.json",
    _I18N / "translations" / "ru.json",
    _I18N / "translations" / "uk.json",
]


class _Coord:
    def __init__(self, data):
        self.data = data
        self.last_update_success = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


class _Charger:
    ip = "1.2.3.4"
    model_name = "V2"
    capabilities: set = set()


def _sensor(data):
    return ChargeReasonSensor(
        _Coord(data), _Charger(), _CHARGE_REASON_DESCRIPTION, "smoke", "e1"
    )


def _value(**data):
    return _sensor(data).native_value


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #

def test_a_limit_wins_over_the_state_that_contradicts_it():
    """Criterion 1 — the measured live frame, and the whole reason for the
    inversion. Reverting to state-first turns this red and nothing else."""
    assert _value(state="charge_complete", subState="limited_by_user") == "limited_by_user"


def test_no_limit_falls_back_to_the_state():
    assert _value(state="charging", subState="no_limits") == "charging"


def test_a_limit_that_does_not_stop_the_charge_is_still_reported():
    """Criterion 3 — deliberate.

    KB-02 puts adaptive throttling at precedence level 7: it reduces current,
    never stops. Folding it into "charging" would hide the only place the
    controlling authority is visible at all. The translation words it as
    throttling rather than "paused" for exactly this reason.
    """
    assert _value(state="charging", subState="paused_by_adaptive_mode") == "paused_by_adaptive_mode"


def test_a_limit_is_reported_with_the_cable_out_too():
    """Criterion 3-bis — pins the consequence of subState winning
    unconditionally, so the behaviour is chosen rather than accidental."""
    assert _value(state="standby", subState="limited_by_user") == "limited_by_user"


def test_an_error_is_one_value_with_the_name_as_an_attribute():
    """Criterion 4 — the two code spaces must not merge.

    state == "error" <=> transform_data mapped subState through the ERROR table,
    so this branch has to come first. Expanding those 15 codes into options
    would be the flat single-table mapping KB-02 calls wrong.
    """
    sensor = _sensor({"state": "error", "subState": "grounding_error"})
    assert sensor.native_value == "error"
    assert sensor.extra_state_attributes == {"error": "grounding_error"}


def test_the_error_attribute_is_absent_outside_the_error_branch():
    assert _sensor({"state": "charging", "subState": "no_limits"}).extra_state_attributes is None


def test_a_plugged_car_with_nothing_asserted_is_waiting():
    assert _value(state="connected", subState="no_limits") == "waiting_for_car"


def test_an_unreadable_substate_is_not_papered_over_by_the_state():
    """Criterion 6 — which authority holds the charge is unknown, and the state
    does not substitute for that."""
    assert _value(state="standby", subState="unknown") == "unknown"


def test_no_data_reports_nothing():
    """Criterion 7. `if not data`, not `data is None`: an empty dict is not a
    frame either, and every other sensor in the file guards it this way."""
    assert _sensor(None).native_value is None
    assert _sensor({}).native_value is None


# --------------------------------------------------------------------------- #
# Mechanical guards — these exist to catch drift, not to describe behaviour
# --------------------------------------------------------------------------- #

def test_every_value_the_rule_can_emit_is_an_option():
    """Criterion 8. HA raises ValueError on a state outside options."""
    emitted = (
        set(V2_SUBSTATE_LIMIT_MAP.values())
        - {"no_limits"}
        | set(_STATE_FALLBACK.values())
        | {"error", "unknown"}
    )
    assert emitted <= set(_CHARGE_REASON_OPTIONS)
    assert len(_CHARGE_REASON_OPTIONS) == 18
    assert "no_limits" not in _CHARGE_REASON_OPTIONS, "the rule never emits it"


def test_every_state_the_station_can_report_has_a_fallback():
    """Criterion 8-bis — the direction criterion 8 does not cover.

    The fallback is a hand-written parallel table to V2_STATE_MAP (it cannot be
    derived: standby -> cable_not_connected is not the identity). KB-02 keeps
    "paused" queued for a rename to the vendor's "disabled"; after such a rename
    the table would silently fall through to "unknown" and no behavioural test
    would notice.
    """
    expected = set(V2_STATE_MAP.values()) - {"error"}
    assert expected == set(_STATE_FALLBACK), (
        "a state map value has no reason to fall back to"
    )


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_every_option_is_translated_in_every_file(path):
    """Criterion 9 — the file had no key-parity test at all before this.

    18 values across four files is the likeliest way this item goes wrong, and
    nothing in the repo would have caught it.
    """
    block = json.loads(path.read_text(encoding="utf-8"))["entity"]["sensor"]["charge_reason"]
    assert block["name"], f"{path.name}: no display name"
    assert set(block["state"]) == set(_CHARGE_REASON_OPTIONS), (
        f"{path.name}: translated keys do not match options"
    )
    assert all(block["state"].values()), f"{path.name}: an empty translation"


def test_the_display_name_is_not_baked_into_the_registry_id():
    """unique_id is built from description.name, not from key (entity.py), so a
    human-readable name here would live in the registry id forever."""
    assert _CHARGE_REASON_DESCRIPTION.name == "charge_reason"
    assert _CHARGE_REASON_DESCRIPTION.name == _CHARGE_REASON_DESCRIPTION.key
