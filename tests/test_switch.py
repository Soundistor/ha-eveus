"""ChargerSwitch: optimistic state and how it gives way to the real value.

The station discards the next 2-3 responses after any write and keeps serving
the old value, so the optimistic state has to outlive the first poll that
follows — but not forever, or a write the station simply ignored would never
show up. Nothing covered this before; the snapshot pins the initial state, not
the behaviour under an action.
"""
from __future__ import annotations

from custom_components.eveus.switch import ChargerSwitch


class _Coord:
    def __init__(self):
        self.data: dict = {"evseEnabled": 0}
        self.last_update_success = True
        self.deferred = 0

    def async_add_listener(self, update_callback, context=None):
        return lambda: None

    def schedule_refresh_after_write(self) -> None:
        self.deferred += 1


class _Charger:
    ip = "1.2.3.4"
    model_name = "V2"
    capabilities = {"charge_switch"}

    def __init__(self):
        self.written: list[bool] = []

    async def set_enabled(self, enabled: bool) -> None:
        self.written.append(enabled)

    def is_charging_active(self, enabled_value) -> bool:
        # V2 polarity: 0 means charging is allowed.
        return enabled_value == 0


def _switch():
    coord = _Coord()
    switch = ChargerSwitch(coord, _Charger(), "smoke", "e1")
    switch.async_write_ha_state = lambda: None
    return switch, coord


def test_reads_v2_polarity():
    switch, coord = _switch()
    assert switch.is_on is True          # evseEnabled 0 -> charging allowed
    coord.data = {"evseEnabled": 1}
    assert switch.is_on is False


async def test_turn_off_shows_immediately_and_defers_the_refresh():
    switch, coord = _switch()

    await switch.async_turn_off()

    assert switch._charger.written == [False]
    assert switch.is_on is False, "the UI must not wait for the next poll"
    assert coord.deferred == 1, "an immediate refresh would read the stale value"


async def test_optimistic_state_outlives_a_stale_poll():
    """The whole point: the first poll after a write still says the old thing."""
    switch, coord = _switch()

    await switch.async_turn_off()
    coord.data = {"evseEnabled": 0}       # station still reports "charging"
    switch._handle_coordinator_update()

    assert switch.is_on is False, "one stale poll must not spring the toggle back"


async def test_optimistic_state_yields_once_the_poll_agrees():
    switch, coord = _switch()

    await switch.async_turn_off()
    coord.data = {"evseEnabled": 1}       # station caught up
    switch._handle_coordinator_update()

    assert switch._optimistic is None, "no reason to keep guessing once confirmed"
    assert switch.is_on is False


async def test_optimistic_state_is_bounded():
    """A write the station ignored must not be shown forever."""
    switch, coord = _switch()

    await switch.async_turn_off()
    coord.data = {"evseEnabled": 0}
    for _ in range(ChargerSwitch._OPTIMISTIC_MAX_POLLS):
        switch._handle_coordinator_update()

    assert switch._optimistic is None
    assert switch.is_on is True, "reality wins in the end"
