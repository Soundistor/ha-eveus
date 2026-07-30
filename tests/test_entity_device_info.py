"""EveusEntity.device_info: sw_version must not carry the firmware's padding."""
from __future__ import annotations

import pytest

from custom_components.eveus.entity import EveusEntity


class _Coord:
    def __init__(self, data: dict | None):
        self.data = data
        self.last_update_success = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


class _Charger:
    ip = "1.2.3.4"
    model_name = "V2"
    sw_version = None


def _device_info(data: dict | None, charger: _Charger | None = None) -> dict:
    return EveusEntity(_Coord(data), charger or _Charger(), "smoke", "e1", "k").device_info


def test_sw_version_is_stripped():
    assert _device_info({"verFWMain": "GRM070A-R3.02.9 "})["sw_version"] == "GRM070A-R3.02.9"


@pytest.mark.parametrize("data", [{}, None])
def test_sw_version_missing(data):
    assert _device_info(data)["sw_version"] is None


def test_sw_version_falls_back_to_the_charger():
    """V1 has no verFWMain — it reads its version off the page it serves."""
    charger = _Charger()
    charger.sw_version = "EnergyStar V5.23"
    assert _device_info({}, charger)["sw_version"] == "EnergyStar V5.23"


def test_main_wins_over_the_fallback():
    charger = _Charger()
    charger.sw_version = "EnergyStar V5.23"
    info = _device_info({"verFWMain": "GRM070A-R3.02.9 "}, charger)
    assert info["sw_version"] == "GRM070A-R3.02.9"
