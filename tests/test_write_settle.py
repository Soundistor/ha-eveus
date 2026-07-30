"""A write is followed by a DELAYED refresh, not an immediate one.

/main serves cached values for a couple of poll cycles after a write — the
station's own web client discards the next 2 responses (3 after a current
change). Refreshing the instant the write returns therefore reads the old
value back and undoes what the user just did on screen.
"""
from __future__ import annotations

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.eveus.coordinator import WRITE_SETTLE


class _Charger:
    ip = "1.2.3.4"
    model_name = "Test"
    capabilities: set = set()
    min_current = 6

    def __init__(self) -> None:
        self.written: list[int] = []

    async def set_current(self, value: int) -> None:
        self.written.append(value)


async def _number(hass, monkeypatch):
    from custom_components.eveus.coordinator import ChargerCoordinator
    from custom_components.eveus.number import ChargerCurrentNumber

    charger = _Charger()
    coordinator = ChargerCoordinator(hass, charger, "e1", "test")
    coordinator.data = {"currentSet": 10, "curDesign": 32}
    refreshes: list[int] = []

    async def _count_refresh() -> None:
        refreshes.append(1)

    monkeypatch.setattr(coordinator, "async_request_refresh", _count_refresh)
    number = ChargerCurrentNumber(coordinator, charger, "smoke", "e1")
    number.hass = hass
    number.async_write_ha_state = lambda: None
    return number, charger, refreshes


async def test_refresh_is_deferred_until_the_station_settles(hass, monkeypatch):
    number, charger, refreshes = await _number(hass, monkeypatch)

    await number.async_set_value(16)
    await hass.async_block_till_done()

    assert charger.written == [16], "the write itself must be immediate"
    assert not refreshes, "refreshing straight away would read the stale value"

    async_fire_time_changed(hass, dt_util.utcnow() + WRITE_SETTLE)
    await hass.async_block_till_done()

    assert refreshes == [1]
