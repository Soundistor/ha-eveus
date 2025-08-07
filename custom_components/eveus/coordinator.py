"""DataUpdateCoordinator – единственная точка получения данных от зарядки."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

class ChargerCoordinator(DataUpdateCoordinator):
    """Координатор запрашивает статус по расписанию."""

    def __init__(self,
                 hass: HomeAssistant,
                 charger,
                 update_interval: int = 30) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="EV charger",
            update_interval=timedelta(seconds=update_interval),
        )
        self.charger = charger

    async def _async_update_data(self):
        """Запросить fresh‑данные у зарядки."""
        try:
            return await self.charger.get_status()
        except Exception as exc:   # pylint: disable=broad-except
            raise UpdateFailed(f"Не удалось получить статус: {exc}") from exc