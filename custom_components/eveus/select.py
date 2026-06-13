"""SelectEntity – AI mode."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

SELECT_DESCRIPTION = SelectEntityDescription(
    key="aiStatus",
    name="ai_mode",
    translation_key="ai_mode",
    icon="mdi:brain",
)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    prefix = data.get("prefix", "")
    async_add_entities(
        [ChargerAIModeSelect(data["coordinator"], data["charger"], prefix, entry.entry_id)],
        True,
    )


class ChargerAIModeSelect(CoordinatorEntity, SelectEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator, charger, prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        self.entity_description = SELECT_DESCRIPTION
        uid = f"{prefix}_ai_mode" if prefix else f"{entry_id}_ai_mode"
        self._attr_unique_id = uid

    @property
    def options(self) -> list[str]:
        return list(self._charger.ai_modes.keys())

    @property
    def current_option(self) -> str | None:
        # transform_data already mapped aiStatus to a string like "Off", "Voltage"
        return self.coordinator.data.get("aiStatus")

    async def async_select_option(self, option: str) -> None:
        mode = self._charger.ai_modes[option]
        await self._charger.set_ai_mode(mode)
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._charger.ip)},
            name=f"Eveus {self._charger.ip}",
            manufacturer="Eveus",
            model=self._charger.model_name,
            configuration_url=f"http://{self._charger.ip}",
        )
