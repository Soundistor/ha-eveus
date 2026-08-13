"""ChargerButton dispatches on the description key, and the two keys differ.

force_refresh only asks the coordinator to poll now — useful precisely while the
station is unreachable, so it must stay available and must not be deferred.
sync_time writes to the station, so it behaves like every other write.
"""
from __future__ import annotations

from custom_components.eveus.button import (
    BUTTON_FORCE_REFRESH,
    BUTTON_SYNC_TIME,
    ChargerButton,
)


class _Coord:
    def __init__(self):
        self.data: dict = {}
        self.last_update_success = True
        self.refreshes = 0
        self.deferred = 0

    def async_add_listener(self, update_callback, context=None):
        return lambda: None

    async def async_request_refresh(self) -> None:
        self.refreshes += 1

    def schedule_refresh_after_write(self) -> None:
        self.deferred += 1


class _Charger:
    ip = "1.2.3.4"
    model_name = "V2"
    capabilities = {"sync_time"}

    def __init__(self):
        self.synced = 0

    async def sync_time(self) -> None:
        self.synced += 1


def _button(description):
    coord = _Coord()
    button = ChargerButton(coord, _Charger(), description, "smoke", "e1")
    button.async_write_ha_state = lambda: None
    return button, coord


async def test_force_refresh_polls_now():
    button, coord = _button(BUTTON_FORCE_REFRESH)

    await button.async_press()

    assert coord.refreshes == 1
    assert coord.deferred == 0, "there is nothing to settle — nothing was written"
    assert button._charger.synced == 0, "the keys must not cross-dispatch"


async def test_sync_time_writes_and_defers():
    button, coord = _button(BUTTON_SYNC_TIME)

    await button.async_press()

    assert button._charger.synced == 1
    assert coord.deferred == 1
    assert coord.refreshes == 0


def test_force_refresh_survives_an_offline_station():
    button, coord = _button(BUTTON_FORCE_REFRESH)
    coord.last_update_success = False
    assert button.available is True, "polling now is exactly what offline needs"


def test_sync_time_follows_the_station():
    button, coord = _button(BUTTON_SYNC_TIME)
    coord.last_update_success = False
    assert button.available is False, "a write to an unreachable station is not offerable"
