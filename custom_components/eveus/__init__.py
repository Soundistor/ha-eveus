import logging
import httpx
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Eveus from a config entry."""
    coordinator = EveusCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "sensor")
    )
    return True

class EveusCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Eveus API."""

    def __init__(self, hass, entry):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self._entry = entry
        self._client = httpx.AsyncClient()

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            response = await self._client.post(
                f"{self._entry.data['host']}/main",
                auth=(self._entry.data['username'], self._entry.data['password']),
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as ex:
            _LOGGER.error("Error fetching data: %s", ex)
            raise