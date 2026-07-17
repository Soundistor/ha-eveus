"""Общий базовый класс сущностей Eveus: device_info + unique_id."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, friendly_device_name


class EveusEntity(CoordinatorEntity):
    """Base for all Eveus entities: shared device_info and unique_id factory."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, charger, prefix: str, entry_id: str, key: str):
        super().__init__(coordinator)
        self._charger = charger
        self._entry_id = entry_id
        self._device_name = friendly_device_name(prefix, charger.ip)
        self._attr_unique_id = f"{prefix}_{key}" if prefix else f"{entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer="Eveus",
            model=self._charger.model_name,
            sw_version=self.coordinator.data.get("verFWMain") if self.coordinator.data else None,
            configuration_url=f"http://{self._charger.ip}",
        )
