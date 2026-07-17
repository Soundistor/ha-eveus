"""Switch – включение/выключение зарядки."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EveusConfigEntry
from .entity import EveusEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    prefix = data.prefix
    async_add_entities([ChargerSwitch(data.coordinator, data.charger, prefix, entry.entry_id)], True)


class ChargerSwitch(EveusEntity, SwitchEntity):

    _attr_translation_key = "charging"

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator, charger, prefix, entry_id, "charging")
        # Optimistic state shown until the next coordinator poll confirms it
        self._optimistic: bool | None = None

    @property
    def is_on(self) -> bool:
        if self._optimistic is not None:
            return self._optimistic
        enabled = self.coordinator.data.get("evseEnabled")
        if enabled is None:
            return False
        return self._charger.is_charging_active(enabled)

    async def async_turn_on(self, **kwargs):
        await self._charger.set_enabled(True)
        self._optimistic = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self._charger.set_enabled(False)
        self._optimistic = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()
