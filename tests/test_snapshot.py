"""Snapshot tests: full entity set + states for V1 and V2 (frozen clock).

Sets up the integration with the sanitized /main fixtures as the charger
response and snapshots (a) the entity-registry summary — including
disabled-by-default entities — and (b) all entity states. Time is frozen so the
clock-derived sensors (TimeDriftSensor, daily sensors, systemTime) are
deterministic. Any unintended change to the entity contract breaks the test.

The /main bodies live in tests/fixtures/{v1,v2}_main.json — committed and
device-identifiers scrubbed — so these snapshots run in CI too.

Regenerate after an intentional contract change:
    python -m pytest tests/test_snapshot.py --snapshot-update
"""
from __future__ import annotations

import json
from pathlib import Path

from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.eveus.const import DOMAIN

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_FROZEN = "2026-07-01T12:00:00+00:00"


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


def _main_body_for(family: str) -> dict:
    """Load the /main body for a firmware family from the committed fixtures."""
    return json.loads((_FIXTURES / f"{family}_main.json").read_text(encoding="utf-8"))


async def _setup(hass, monkeypatch, model, raw, entry_id):
    async def _fake(self):
        return dict(raw)

    monkeypatch.setattr("custom_components.eveus.charger.v1.ChargerV1.get_status", _fake)
    monkeypatch.setattr("custom_components.eveus.charger.v2.ChargerV2.get_status", _fake)

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        data={
            "ip_address": "1.2.3.4",
            "model": model,
            "username": "admin",
            "password": "secret",
            "device_prefix": "",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _assert_snapshot(hass, entry, snapshot):
    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert entries, "no entities registered for the config entry"
    registry = sorted(
        (
            e.entity_id,
            e.unique_id,
            str(e.entity_category),
            e.original_name,
            bool(e.disabled_by),
        )
        for e in entries
    )
    assert registry == snapshot(name="registry")
    states = sorted(hass.states.async_all(), key=lambda s: s.entity_id)
    assert states == snapshot(name="states")


async def test_snapshot_v2(hass, snapshot, freezer, monkeypatch):
    freezer.move_to(_FROZEN)
    entry = await _setup(hass, monkeypatch, "v2", _main_body_for("v2"), "e_v2")
    await _assert_snapshot(hass, entry, snapshot)


async def test_snapshot_v1(hass, snapshot, freezer, monkeypatch):
    freezer.move_to(_FROZEN)
    entry = await _setup(hass, monkeypatch, "v1", _main_body_for("v1"), "e_v1")
    await _assert_snapshot(hass, entry, snapshot)
