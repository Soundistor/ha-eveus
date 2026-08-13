"""A write is followed by a DELAYED refresh, not an immediate one.

/main serves cached values for a couple of poll cycles after a write — the
station's own web client discards the next 2 responses (3 after a current
change). Refreshing the instant the write returns therefore reads the old
value back and undoes what the user just did on screen.

Every write path is covered: the fix landed in five places and only one of them
was tested, so a revert to async_request_refresh() in the other four would have
gone unnoticed. The paths differ in constructor and in the charger method they
call, so the parametrization is over (entity factory, action), not over a value.
"""
from __future__ import annotations

from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.eveus.coordinator import WRITE_SETTLE


class _Charger:
    ip = "1.2.3.4"
    model_name = "Test"
    capabilities = {"charge_switch", "sync_time"}
    min_current = 6
    ai_modes = {"off": 0, "voltage": 1, "tesla_auto": 2, "power": 3}

    def __init__(self) -> None:
        self.written: list = []

    async def set_current(self, value: int) -> None:
        self.written.append(("current", value))

    async def set_enabled(self, enabled: bool) -> None:
        self.written.append(("enabled", enabled))

    async def set_ai_mode(self, mode: int) -> None:
        self.written.append(("ai_mode", mode))

    async def sync_time(self) -> None:
        self.written.append(("sync_time", None))

    def is_charging_active(self, enabled_value) -> bool:
        return bool(enabled_value)


def _coordinator(hass, charger, monkeypatch):
    from custom_components.eveus.coordinator import ChargerCoordinator

    coordinator = ChargerCoordinator(hass, charger, "e1", "test")
    coordinator.data = {"currentSet": 10, "curDesign": 32, "evseEnabled": 1, "aiStatus": "off"}
    refreshes: list[int] = []

    async def _count_refresh() -> None:
        refreshes.append(1)

    monkeypatch.setattr(coordinator, "async_request_refresh", _count_refresh)
    return coordinator, refreshes


def _build(cls, coordinator, charger, *args):
    entity = cls(coordinator, charger, *args)
    entity.async_write_ha_state = lambda: None
    return entity


def _number(coordinator, charger):
    from custom_components.eveus.number import ChargerCurrentNumber

    number = _build(ChargerCurrentNumber, coordinator, charger, "smoke", "e1")
    return number, lambda: number.async_set_native_value(16), ("current", 16)


def _switch_on(coordinator, charger):
    from custom_components.eveus.switch import ChargerSwitch

    switch = _build(ChargerSwitch, coordinator, charger, "smoke", "e1")
    return switch, switch.async_turn_on, ("enabled", True)


def _switch_off(coordinator, charger):
    from custom_components.eveus.switch import ChargerSwitch

    switch = _build(ChargerSwitch, coordinator, charger, "smoke", "e1")
    return switch, switch.async_turn_off, ("enabled", False)


def _select(coordinator, charger):
    from custom_components.eveus.select import ChargerAIModeSelect

    select = _build(ChargerAIModeSelect, coordinator, charger, "smoke", "e1")
    return select, lambda: select.async_select_option("power"), ("ai_mode", 3)


def _sync_time_button(coordinator, charger):
    from custom_components.eveus.button import BUTTON_SYNC_TIME, ChargerButton

    button = _build(ChargerButton, coordinator, charger, BUTTON_SYNC_TIME, "smoke", "e1")
    return button, button.async_press, ("sync_time", None)


_WRITE_PATHS = [
    pytest.param(_number, id="number.set_value"),
    pytest.param(_switch_on, id="switch.turn_on"),
    pytest.param(_switch_off, id="switch.turn_off"),
    pytest.param(_select, id="select.select_option"),
    pytest.param(_sync_time_button, id="button.sync_time"),
]


@pytest.mark.parametrize("factory", _WRITE_PATHS)
async def test_refresh_is_deferred_until_the_station_settles(hass, monkeypatch, factory):
    charger = _Charger()
    coordinator, refreshes = _coordinator(hass, charger, monkeypatch)
    entity, action, expected_write = factory(coordinator, charger)
    entity.hass = hass

    await action()
    await hass.async_block_till_done()

    assert charger.written == [expected_write], "the write itself must be immediate"
    assert not refreshes, "refreshing straight away would read the stale value"

    async_fire_time_changed(hass, dt_util.utcnow() + WRITE_SETTLE)
    await hass.async_block_till_done()

    assert refreshes == [1]


async def test_force_refresh_is_not_deferred(hass, monkeypatch):
    """The one button that must poll now, not in three seconds."""
    from custom_components.eveus.button import BUTTON_FORCE_REFRESH, ChargerButton

    charger = _Charger()
    coordinator, refreshes = _coordinator(hass, charger, monkeypatch)
    button = _build(ChargerButton, coordinator, charger, BUTTON_FORCE_REFRESH, "smoke", "e1")
    button.hass = hass

    await button.async_press()
    await hass.async_block_till_done()

    assert refreshes == [1]
    assert not charger.written
