"""ChargerCurrentNumber bounds: minimum follows the station's minCurrent."""
from __future__ import annotations

import pytest

from custom_components.eveus.number import ChargerCurrentNumber


class _Coord:
    def __init__(self, data: dict | None = None):
        self.data: dict = data or {}
        self.last_update_success = True

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


class _Charger:
    ip = "1.2.3.4"
    model_name = "Test"
    capabilities: set = set()
    min_current = 6


def _make(data: dict | None = None) -> ChargerCurrentNumber:
    number = ChargerCurrentNumber(_Coord(data), _Charger(), "smoke", "e1")
    number.async_write_ha_state = lambda: None
    return number


def test_min_follows_min_current():
    assert _make({"minCurrent": 7}).native_min_value == 7.0


@pytest.mark.parametrize("data", [{}, {"minCurrent": "x"}, {"minCurrent": None}])
def test_min_falls_back_to_charger_constant(data):
    assert _make(data).native_min_value == 6.0
