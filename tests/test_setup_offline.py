"""Setup must not depend on the charger being reachable.

The station is offline most of the time (it comes up for a charging session),
so gating the config entry on the first poll meant almost every HA restart left
it in SETUP_RETRY with no entities at all, and recovery was up to 10 minutes
away — the core's setup-retry backoff doubles to a 600 s ceiling (measured on
prod, 2026-08-13). The entry now loads regardless: the entity set comes from
charger.capabilities, not from poll data.
"""
from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr, issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eveus.const import DOMAIN


@pytest.fixture
def unreachable(monkeypatch):
    """Every request to the station fails the way an absent host fails."""
    async def _fail(self):
        raise aiohttp.ClientConnectionError("Cannot connect to host 1.2.3.4:80")

    for model in ("v1.ChargerV1", "v2.ChargerV2"):
        monkeypatch.setattr(
            f"custom_components.eveus.charger.{model}.get_status", _fail
        )


async def _setup(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "1.2.3.4",
            "model": "v2",
            "username": "admin",
            "password": "secret",
            "device_prefix": "offline",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entry_loads_while_charger_is_unreachable(hass, unreachable):
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED, (
        "an unreachable charger must not leave the entry in SETUP_RETRY"
    )


# Entities that do not read the station and so must survive it being offline:
# the three daily/last-session accumulators serve their own stored values, and
# force_refresh only asks the coordinator to poll now — the one action that is
# useful precisely while the charger is unreachable. Connectivity reports the
# offline state itself.
_SURVIVES_OFFLINE = (
    "connectivity",
    "daily_energy",
    "daily_session_time",
    "last_session_energy",
    "last_session_duration",
    "force_refresh",
)


async def test_entities_exist_and_are_unavailable(hass, unreachable):
    await _setup(hass)

    states = hass.states.async_all()
    assert states, "entities must register even without poll data"
    values = {
        s.entity_id: s.state
        for s in states
        if not s.entity_id.endswith(_SURVIVES_OFFLINE)
    }
    assert values, "the station-reading entities must still be in the sample"
    assert set(values.values()) == {STATE_UNAVAILABLE}, values


async def test_own_value_entities_stay_available_offline(hass, unreachable):
    """Going unavailable with the station wipes the entity's attributes.

    That is what made persisting the daily values separately necessary; these
    entities never needed the station in the first place.
    """
    await _setup(hass)

    survivors = {
        s.entity_id: s.state
        for s in hass.states.async_all()
        if s.entity_id.endswith(_SURVIVES_OFFLINE)
    }
    assert len(survivors) == len(_SURVIVES_OFFLINE), survivors
    assert STATE_UNAVAILABLE not in survivors.values(), survivors


async def test_no_repair_issue_for_an_unreachable_charger(hass, unreachable):
    entry = await _setup(hass)

    issues = ir.async_get(hass).issues
    assert not [k for k in issues if k[0] == DOMAIN], (
        "being offline is normal for this device — it must not raise a repair issue"
    )
    assert entry.state is ConfigEntryState.LOADED


async def test_setup_clears_legacy_repair_issues(hass, unreachable):
    """Issue ids no version raises any more used to sit in .storage forever.

    Prod diagnostics on 2026-08-13 still carried a live `cannot_connect` issue
    created 2026-06-14; `device_error` is the pre-2026-07-17 shared id, before it
    gained a per-entry suffix.
    """
    registry = ir.async_get(hass)
    for legacy in ("cannot_connect", "device_error"):
        registry.async_get_or_create(
            DOMAIN, legacy, is_fixable=False, is_persistent=False,
            severity=ir.IssueSeverity.ERROR, translation_key="device_error",
        )

    await _setup(hass)

    for legacy in ("cannot_connect", "device_error"):
        assert registry.async_get_issue(DOMAIN, legacy) is None, legacy


async def test_reading_every_entity_survives_missing_data(hass, unreachable):
    """No value property may explode while coordinator.data is None.

    Before this change the first poll always succeeded, so these paths were
    unreachable; now they are the normal startup state. Pushing None as a
    *successful* update is the hostile case: the entities are available, so HA
    really does read native_value / is_on / capability attributes.
    """
    entry = await _setup(hass)

    entry.runtime_data.coordinator.async_set_updated_data(None)
    await hass.async_block_till_done()

    states = hass.states.async_all()
    assert states
    for state in states:
        assert state.state != "unavailable" or state.entity_id.endswith("connectivity")


async def test_daily_energy_survives_an_offline_unload_setup_cycle(hass, unreachable, monkeypatch):
    """The seam between the two offline fixes, through the real platform path.

    Both halves were only ever tested in isolation: this file never built a
    DailyEnergySensor, and test_daily_sensors.py drives one over a hand-rolled
    stub coordinator instead of hass.config_entries. What is proven here is that
    the sensor reaches async_added_to_hass at all when the entry loads with an
    unreachable station, and that a real unload/setup cycle carries its stored
    day across.
    """
    entry = await _setup(hass)
    entity_id = "sensor.offline_daily_energy"

    # One good frame so there is a day to lose, then back offline.
    async def _ok(self):
        return {"state": 2, "totalEnergy": 100.0, "verFWWifi": "1PGRW001A-R3.02.9"}

    monkeypatch.setattr("custom_components.eveus.charger.v2.ChargerV2.get_status", _ok)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    async def _ok_more(self):
        return {"state": 2, "totalEnergy": 105.5, "verFWWifi": "1PGRW001A-R3.02.9"}

    monkeypatch.setattr("custom_components.eveus.charger.v2.ChargerV2.get_status", _ok_more)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "5.5"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # A single frame after the restart: the day must continue from the restored
    # baseline, not start over from this reading.
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "5.5"


async def test_sw_version_reaches_the_device_page_after_an_offline_start(
    hass, unreachable, monkeypatch
):
    """HA reads device_info once, at entity registration.

    With setup no longer waiting for the charger, that happens before any
    version exists, so the device page stayed blank until a reload that caught
    the station online.
    """
    from homeassistant.helpers import device_registry as dr

    entry = await _setup(hass)

    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.sw_version is None      # nothing to know yet

    async def _ok(self):
        return {"state": 2, "verFWMain": "GRM070A-R3.05.4 "}

    monkeypatch.setattr("custom_components.eveus.charger.v2.ChargerV2.get_status", _ok)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    # Stripped: the station sends a trailing space, and the two paths into the
    # registry must not disagree about the version string.
    assert device.sw_version == "GRM070A-R3.05.4"


async def test_sw_version_is_written_to_the_registry_only_once(
    hass, unreachable, monkeypatch
):
    entry = await _setup(hass)

    async def _ok(self):
        return {"state": 2, "verFWMain": "GRM070A-R3.05.4"}

    monkeypatch.setattr("custom_components.eveus.charger.v2.ChargerV2.get_status", _ok)

    writes = []
    real_update = dr.DeviceRegistry.async_update_device

    def _counting_update(self, device_id, **kwargs):
        if "sw_version" in kwargs:
            writes.append(kwargs["sw_version"])
        return real_update(self, device_id, **kwargs)

    monkeypatch.setattr(dr.DeviceRegistry, "async_update_device", _counting_update)

    for _ in range(3):
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    assert writes == ["GRM070A-R3.05.4"], writes
