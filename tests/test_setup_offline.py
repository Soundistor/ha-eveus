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
from homeassistant.helpers import issue_registry as ir
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


async def test_entities_exist_and_are_unavailable(hass, unreachable):
    await _setup(hass)

    states = hass.states.async_all()
    assert states, "entities must register even without poll data"
    # Connectivity reports the offline state itself, so it stays available.
    values = {
        s.entity_id: s.state for s in states if not s.entity_id.endswith("connectivity")
    }
    assert set(values.values()) == {STATE_UNAVAILABLE}, values


async def test_no_repair_issue_for_an_unreachable_charger(hass, unreachable):
    entry = await _setup(hass)

    issues = ir.async_get(hass).issues
    assert not [k for k in issues if k[0] == DOMAIN], (
        "being offline is normal for this device — it must not raise a repair issue"
    )
    assert entry.state is ConfigEntryState.LOADED


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
