"""ChargerAIModeSelect: options come from the generation, not the shared map.

The fallback matters on real hardware: V1 exposes two AI modes, but its aiStatus
is decoded through the shared four-value map, so "tesla_auto" is reachable on a
V1 station. Returning it as current_option would make HA raise on a value that
is not in options.
"""
from __future__ import annotations

import pytest

from custom_components.eveus.select import ChargerAIModeSelect


class _Coord:
    def __init__(self, data=None):
        self.data = {} if data is None else data
        self.last_update_success = True
        self.deferred = 0

    def async_add_listener(self, update_callback, context=None):
        return lambda: None

    def schedule_refresh_after_write(self) -> None:
        self.deferred += 1


class _Charger:
    ip = "1.2.3.4"
    model_name = "V1"
    capabilities: set = set()
    ai_modes = {"off": 0, "voltage": 1}      # V1 knows two

    def __init__(self):
        self.written: list[int] = []

    async def set_ai_mode(self, mode: int) -> None:
        self.written.append(mode)


def _select(data=None):
    coord = _Coord(data)
    select = ChargerAIModeSelect(coord, _Charger(), "smoke", "e1")
    select.async_write_ha_state = lambda: None
    return select, coord


def test_options_are_the_generations_own():
    select, _ = _select()
    assert select.options == ["off", "voltage"]


def test_reads_a_known_option():
    select, _ = _select({"aiStatus": "voltage"})
    assert select.current_option == "voltage"


@pytest.mark.parametrize("value", ["tesla_auto", "power", "unknown"])
def test_value_outside_this_models_options_reads_as_none(value):
    """V1 firmware really can report a mode V1 does not have."""
    select, _ = _select({"aiStatus": value})
    assert select.current_option is None


def test_no_data_reads_as_none():
    select, _ = _select()
    assert select.current_option is None


async def test_selecting_writes_the_numeric_mode_and_defers_the_refresh():
    select, coord = _select({"aiStatus": "off"})

    await select.async_select_option("voltage")

    assert select._charger.written == [1]
    assert coord.deferred == 1
