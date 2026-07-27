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


def _device_info(data: dict | None) -> dict:
    return EveusEntity(_Coord(data), _Charger(), "smoke", "e1", "k").device_info


def test_sw_version_is_stripped():
    assert _device_info({"verFWMain": "GRM070A-R3.02.9 "})["sw_version"] == "GRM070A-R3.02.9"


@pytest.mark.parametrize("data", [{}, None])
def test_sw_version_missing(data):
    assert _device_info(data)["sw_version"] is None
