"""NumberEntity – регулятор тока зарядки."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EveusConfigEntry
from .entity import EveusEntity

PARALLEL_UPDATES = 0

NUMBER_DESCRIPTION = NumberEntityDescription(
    key="currentSet",
    name="current_set",
    translation_key="current_set",
    native_step=1,
    native_unit_of_measurement="A",
    icon="mdi:current-ac",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    prefix = data.prefix
    async_add_entities(
        [ChargerCurrentNumber(data.coordinator, data.charger, prefix, entry.entry_id)],
        True,
    )


class ChargerCurrentNumber(EveusEntity, NumberEntity):

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator, charger, prefix, entry_id, "current_set")
        self.entity_description = NUMBER_DESCRIPTION

    @property
    def native_min_value(self) -> float:
        return self._charger.min_current

    @property
    def native_max_value(self) -> float:
        design = self.coordinator.data.get("curDesign") if self.coordinator.data else None
        try:
            return float(design) if design else 32.0
        except (ValueError, TypeError):
            return 32.0

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("currentSet")

    async def async_set_value(self, value: float) -> None:
        await self._charger.set_current(int(value))
        await self.coordinator.async_request_refresh()
