"""Smoke test proving the phacc `hass` fixture works end to end.

This is infrastructure proof, not integration coverage: it wires up the eveus
config entry with the charger's HTTP call mocked out, then asserts Home
Assistant set the integration up and produced at least one entity state.
"""
from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eveus.const import DOMAIN

# A full-enough V2 /main payload: every key the V2 charger declares, with
# numeric values transform_data can map. Keeps entity setup from choking on
# missing fields.
_V2_RAW = {
    "evseEnabled": 1,
    "state": 2,          # standby
    "subState": 0,       # no_limits
    "currentSet": 16,
    "curDesign": 32,
    "curMeas1": 0,
    "voltMeas1": 230,
    "powerMeas": 0,
    "temperature1": 25,
    "temperature2": 30,
    "aiStatus": 0,
    "aiVoltage": 230,
    "ground": 1,
    "groundCtrl": 1,
    "sessionTime": 0,
    "sessionEnergy": 0,
    "totalEnergy": 1234,
    "systemTime": 1751884800,
    "leakValue": 0,
    "vBat": 3300,
    "RSSI": -55,
    "IEM1": 0,
    "IEM2": 0,
}


@pytest.fixture
def _mock_get_status(monkeypatch):
    async def _fake_get_status(self):
        return dict(_V2_RAW)

    monkeypatch.setattr(
        "custom_components.eveus.charger.v2.ChargerV2.get_status",
        _fake_get_status,
    )


async def test_config_entry_setup_creates_entities(hass, _mock_get_status):
    """Full integration setup succeeds and yields at least one entity state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "1.2.3.4",
            "model": "v2",
            "username": "admin",
            "password": "secret",
            "device_prefix": "smoke",
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is not None
    states = hass.states.async_all()
    assert states, "expected at least one entity state after setup"
