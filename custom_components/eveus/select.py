"""SelectEntity – AI mode."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EveusConfigEntry
from .entity import EveusEntity

PARALLEL_UPDATES = 0

SELECT_DESCRIPTION = SelectEntityDescription(
    key="aiStatus",
    name="ai_mode",
    translation_key="ai_mode",
    icon="mdi:brain",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    prefix = data.prefix
    async_add_entities(
        [ChargerAIModeSelect(data.coordinator, data.charger, prefix, entry.entry_id)],
        True,
    )


class ChargerAIModeSelect(EveusEntity, SelectEntity):

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator, charger, prefix, entry_id, "ai_mode")
        self.entity_description = SELECT_DESCRIPTION

    @property
    def options(self) -> list[str]:
        return list(self._charger.ai_modes.keys())

    @property
    def current_option(self) -> str | None:
        # transform_data already mapped aiStatus to a key like "off", "voltage".
        # Guard against values outside this model's options (e.g. "tesla_auto"
        # reported by V1 firmware, or "unknown").
        value = self.coordinator.data.get("aiStatus")
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        mode = self._charger.ai_modes[option]
        await self._charger.set_ai_mode(mode)
        await self.coordinator.async_request_refresh()
