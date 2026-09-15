"""Общий базовый класс сущностей Eveus: device_info + unique_id."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, friendly_device_name


def firmware_version(coordinator_data, charger):
    """The firmware version to publish, or None if it is not known yet.

    The station sends verFWMain with a trailing space ("GRM070A-R3.05.4 ").
    V1 has no such field — it reports its version only in the web UI it serves,
    which the charger reads on the first successful poll.

    Shared with the coordinator, which writes the version straight into the
    device registry after an offline start: two copies of this rule would drift
    into two different version strings for the same station.
    """
    version = coordinator_data.get("verFWMain") if coordinator_data else None
    if not version:
        version = charger.sw_version
    return version.strip() if isinstance(version, str) else version


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
        info = DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer="Eveus",
            model=self._charger.model_name,
            configuration_url=f"http://{self._charger.ip}",
        )
        # The key goes in only when there is a version to put there. DeviceInfo
        # is a total=False TypedDict and the registry reads the two cases
        # differently: an absent key means "leave whatever is stored", an
        # explicit None means "erase it". Always sending the second wiped a
        # known version off the device page on every start that found the
        # station offline — which, for this device, is the normal way to start.
        # The next successful poll writes it back (coordinator), but until then
        # the page shows nothing.
        # Falsy, not `is not None`: an empty string is what a frame of padding
        # (`verFWMain: "  "`) leaves after the strip, and writing that would
        # erase a good stored version just as None would. The coordinator's own
        # write path already tests it this way — the two must not disagree
        # about what counts as "no version".
        version = firmware_version(self.coordinator.data, self._charger)
        if version:
            info["sw_version"] = version
        return info
