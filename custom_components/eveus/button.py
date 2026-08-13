"""Кнопки: Force Refresh и Sync Time (обе модели, формат записи разный)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EveusConfigEntry
from .entity import EveusEntity

PARALLEL_UPDATES = 0

BUTTON_FORCE_REFRESH = ButtonEntityDescription(
    key="force_refresh",
    name="force_refresh",
    translation_key="force_refresh",
    icon="mdi:refresh",
)

BUTTON_SYNC_TIME = ButtonEntityDescription(
    key="sync_time",
    name="sync_time",
    translation_key="sync_time",
    icon="mdi:clock-check",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    coordinator = data.coordinator
    charger = data.charger
    prefix = data.prefix

    entities = [ChargerButton(coordinator, charger, BUTTON_FORCE_REFRESH, prefix, entry.entry_id)]
    if "sync_time" in charger.capabilities:
        entities.append(ChargerButton(coordinator, charger, BUTTON_SYNC_TIME, prefix, entry.entry_id))

    async_add_entities(entities, True)


class ChargerButton(EveusEntity, ButtonEntity):

    def __init__(self, coordinator, charger, description: ButtonEntityDescription,
                 prefix: str, entry_id: str):
        super().__init__(coordinator, charger, prefix, entry_id, description.name)
        self.entity_description = description

    @property
    def available(self) -> bool:
        # force_refresh only asks the coordinator to poll now, which is exactly
        # what you want while the charger is unreachable — so it must not go
        # unavailable with it. sync_time does write to the station, so there the
        # inherited availability is correct. Keyed off the description rather
        # than overridden for the whole class, which serves both buttons.
        if self.entity_description.key == "force_refresh":
            return True
        return super().available

    async def async_press(self) -> None:
        if self.entity_description.key == "force_refresh":
            await self.coordinator.async_request_refresh()
        elif self.entity_description.key == "sync_time":
            await self._charger.sync_time()
            self.coordinator.schedule_refresh_after_write()
