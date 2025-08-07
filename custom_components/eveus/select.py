"""SelectEntity – AI‑mode."""

from __future__ import annotations
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

AI_MODES = {
    "Off": 0,
    "Voltage": 1,
    "Tesla (auto)": 2,
    "Power": 3,
}

SELECT_DESCRIPTION = SelectEntityDescription(
    key="ai_mode",
    name="Adaptive mode",
    options=list(AI_MODES.keys()),
    icon="mdi:brain",
)

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    charger = hass.data[DOMAIN][entry.entry_id]["charger"]
    async_add_entities([ChargerAIModeSelect(coordinator, charger)], True)


class ChargerAIModeSelect(CoordinatorEntity, SelectEntity):
    def __init__(self, coordinator, charger):
        super().__init__(coordinator)
        self._charger = charger
        self.entity_description = SELECT_DESCRIPTION
        self._attr_unique_id = f"{charger.ip}-{SELECT_DESCRIPTION.key}"
        self._attr_name = f"{SELECT_DESCRIPTION.name} ({charger.ip})"

    @property
    def current_option(self) -> str | None:
        """Считаем состояние из `aiStatus` (0‑off, 1‑voltage, 2‑auto, 3‑power)."""
        status = self.coordinator.data.get("aiStatus")
        if status is None:
            return None
        # Наименования могут отличаться в разных моделях
        reverse = {v: k for k, v in AI_MODES.items()}
        return reverse.get(int(status))

    async def async_select_option(self, option: str) -> None:
        """Пользователь выбрал вариант → отправляем запрос."""
        mode = AI_MODES[option]
        await self._charger.set_ai_mode(mode)
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._charger.ip)},
            "name": f"EV charger {self._charger.ip}",
            "manufacturer": "YourManufacturer",
            "model": self._charger.__class__.__name__,
        }