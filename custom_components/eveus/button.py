"""Кнопки: Force Refresh и Sync Time (V2 only)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

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


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    charger = data["charger"]
    prefix = data.get("prefix", "")

    entities = [ChargerButton(coordinator, charger, BUTTON_FORCE_REFRESH, prefix, entry.entry_id)]
    if "sync_time" in charger.capabilities:
        entities.append(ChargerButton(coordinator, charger, BUTTON_SYNC_TIME, prefix, entry.entry_id))

    async_add_entities(entities, True)


class ChargerButton(CoordinatorEntity, ButtonEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator, charger, description: ButtonEntityDescription,
                 prefix: str, entry_id: str):
        super().__init__(coordinator)
        self._charger = charger
        self._entry_id = entry_id
        self.entity_description = description
        uid = f"{prefix}_{description.name}" if prefix else f"{entry_id}_{description.name}"
        self._attr_unique_id = uid

    async def async_press(self) -> None:
        if self.entity_description.key == "force_refresh":
            await self.coordinator.async_request_refresh()
        elif self.entity_description.key == "sync_time":
            await self._charger.sync_time()
            await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=f"Eveus {self._charger.ip}",
            manufacturer="Eveus",
            model=self._charger.model_name,
            configuration_url=f"http://{self._charger.ip}",
        )
