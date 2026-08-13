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
    # V1 has no remote stop at all (its own web UI has no such control, and a
    # live `evseEnabled=0` mid-session is ignored), and its evseEnabled reads 1
    # at all times — a toggle there would lie in both directions. Whether a
    # session is running is answered by the state sensor.
    if "charge_switch" not in data.charger.capabilities:
        return
    prefix = data.prefix
    async_add_entities([ChargerSwitch(data.coordinator, data.charger, prefix, entry.entry_id)], True)


class ChargerSwitch(EveusEntity, SwitchEntity):

    _attr_translation_key = "charging"

    # The station discards the next 2-3 responses after any write and keeps
    # serving the old value (KB-01; measured live). At a 30-60s interval that is
    # minutes, so dropping the optimistic state on the first poll that follows
    # made the toggle spring back. Hold it until the poll agrees — bounded, so a
    # write the station simply ignored still loses to reality.
    _OPTIMISTIC_MAX_POLLS = 3

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator, charger, prefix, entry_id, "charging")
        # Optimistic state shown until a coordinator poll confirms it
        self._optimistic: bool | None = None
        self._optimistic_polls = 0

    @property
    def is_on(self) -> bool:
        if self._optimistic is not None:
            return self._optimistic
        if not self.coordinator.data:
            return False
        enabled = self.coordinator.data.get("evseEnabled")
        if enabled is None:
            return False
        return self._charger.is_charging_active(enabled)

    async def async_turn_on(self, **kwargs):
        await self._charger.set_enabled(True)
        self._set_optimistic(True)
        self.coordinator.schedule_refresh_after_write()

    async def async_turn_off(self, **kwargs):
        await self._charger.set_enabled(False)
        self._set_optimistic(False)
        self.coordinator.schedule_refresh_after_write()

    def _set_optimistic(self, value: bool) -> None:
        self._optimistic = value
        self._optimistic_polls = 0
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._optimistic is not None:
            enabled = self.coordinator.data.get("evseEnabled") if self.coordinator.data else None
            polled = (
                self._charger.is_charging_active(enabled) if enabled is not None else None
            )
            self._optimistic_polls += 1
            if polled == self._optimistic or self._optimistic_polls >= self._OPTIMISTIC_MAX_POLLS:
                self._optimistic = None
        super()._handle_coordinator_update()
