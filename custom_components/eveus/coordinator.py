"""DataUpdateCoordinator – единственная точка получения данных от зарядки."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class ChargerCoordinator(DataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, charger, update_interval: int = 30) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="EV charger",
            update_interval=timedelta(seconds=update_interval),
        )
        self.charger = charger

    async def _async_update_data(self):
        try:
            raw = await self.charger.get_status()
            return self.charger.transform_data(raw)
        except Exception as exc:
            raise UpdateFailed(f"Error updating: {exc}") from exc
