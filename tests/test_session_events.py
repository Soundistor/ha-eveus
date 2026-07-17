"""Tests for const.session_transition (loaded standalone, no homeassistant import)."""
import importlib.util
from pathlib import Path

_CONST = Path(__file__).resolve().parents[1] / "custom_components" / "eveus" / "const.py"
_spec = importlib.util.spec_from_file_location("eveus_const", _CONST)
const = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(const)


def test_charging_started_from_standby():
    assert const.session_transition("standby", "charging") == "charging_started"


def test_charging_started_resume_from_paused():
    assert const.session_transition("paused", "charging") == "charging_started"


def test_session_ended_from_charging_to_standby():
    assert const.session_transition("charging", "standby") == "session_ended"


def test_session_ended_from_paused_to_charge_complete():
    assert const.session_transition("paused", "charge_complete") == "session_ended"


def test_session_ended_from_charging_to_error():
    assert const.session_transition("charging", "error") == "session_ended"


def test_no_event_charging_to_paused():
    assert const.session_transition("charging", "paused") is None


def test_no_event_idle_to_idle():
    assert const.session_transition("standby", "connected") is None


def test_no_event_charging_to_charging():
    assert const.session_transition("charging", "charging") is None
