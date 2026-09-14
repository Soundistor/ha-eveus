"""The setpoint the station cannot legally have sent.

Measured 2026-09-10 on V1: the first frame after a restart carried
currentSet = 0 in the same frame that carried totalEnergy = 0, then 12 a minute
later, then 20. Zero is not a low setpoint — the service page offers 6/7/8 as
the minimum and nothing below it is selectable.

The floor is the generation constant on purpose. `number.native_min_value`
reads `minCurrent` out of the same frame we are refusing to trust, and on V1
that key does not exist at all. The cost is spelled out in the last test: a
station configured to 8 A still passes a 7. Lenient, never wrong — and the
test is there so that "tightening" it against the frame goes red.
"""
from __future__ import annotations

import logging

import pytest

from custom_components.eveus.coordinator import ChargerCoordinator


class _Charger:
    ip = "1.2.3.4"
    capabilities: set = set()
    sw_version: str | None = "EnergyStar V5.23"
    sw_version_error: str | None = None

    def __init__(self, min_current: int):
        self.min_current = min_current
        self._data: dict = {}

    def set_data(self, data: dict) -> None:
        self._data = data

    async def get_status(self):
        return dict(self._data)

    async def async_load_sw_version(self) -> None:
        return None

    def transform_data(self, raw):
        return raw


def _coordinator(hass, min_current: int) -> ChargerCoordinator:
    return ChargerCoordinator(hass, _Charger(min_current), "e1", "Eveus Test")


async def _poll(coord: ChargerCoordinator, **data):
    coord.charger.set_data(data)
    return await coord._async_update_data()


async def test_zero_never_reaches_the_entities(hass):
    coord = _coordinator(hass, 7)

    data = await _poll(coord, state="charging", currentSet=0)

    # Dropped, not zeroed and not replaced with the last known value: an absent
    # key gives the entity `unknown`, while a substituted number would be
    # written to statistics as if the station had said it.
    assert "currentSet" not in data
    assert coord._setpoint_dropped == 1


async def test_the_next_real_frame_passes_immediately(hass):
    coord = _coordinator(hass, 7)

    await _poll(coord, state="charging", currentSet=0)
    data = await _poll(coord, state="charging", currentSet=20)

    # No confirmation window, no waiting for a second frame to agree: the
    # guard's whole point is that it needs no memory. A mutation that adds
    # N-of-M confirmation here has to make this red.
    assert data["currentSet"] == 20
    assert coord._setpoint_dropped == 1


@pytest.mark.parametrize("min_current", [6, 7])
async def test_the_generation_minimum_itself_passes(hass, min_current):
    coord = _coordinator(hass, min_current)

    data = await _poll(coord, state="charging", currentSet=min_current)

    # V2 can be set to 6, V1 to 7. Hard-coding either one eats the other
    # generation's legitimate floor.
    assert data["currentSet"] == min_current
    assert coord._setpoint_dropped == 0


async def test_a_configured_minimum_above_the_constant_is_not_enforced(hass):
    coord = _coordinator(hass, 6)

    data = await _poll(coord, state="charging", minCurrent=8, currentSet=7)

    # Deliberate leniency, pinned so it cannot be "fixed" by accident: 7 is
    # below what this station is configured to, and the guard still lets it
    # through. Reading the bound from minCurrent would catch it — and would
    # take the bound from the very frame the guard exists to distrust.
    assert data["currentSet"] == 7
    assert coord._setpoint_dropped == 0


async def test_dropping_leaves_a_warning(hass, caplog):
    coord = _coordinator(hass, 7)

    with caplog.at_level(logging.WARNING):
        await _poll(coord, state="charging", currentSet=0)

    # Silent dropping is the behaviour we hold against the firmware.
    assert "currentSet" in caplog.text


async def test_non_numeric_is_left_alone(hass):
    coord = _coordinator(hass, 7)

    data = await _poll(coord, state="charging", currentSet="garbage")

    # Out of scope by decision, not by oversight: this guard is about a value
    # that parses and is still impossible.
    assert data["currentSet"] == "garbage"
    assert coord._setpoint_dropped == 0
