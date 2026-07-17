"""Snapshot tests: full entity set + states for V1 and V2 (frozen clock).

Sets up the integration with the real mockData /main bodies as the charger
response and snapshots (a) the entity-registry summary — including
disabled-by-default entities — and (b) all entity states. Time is frozen so the
clock-derived sensors (TimeDriftSensor, daily sensors, systemTime) are
deterministic. Any unintended change to the entity contract breaks the test.

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

_MOCKDATA = Path(__file__).resolve().parents[1] / "mockData"
_FROZEN = "2026-07-01T12:00:00+00:00"


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


def _main_body(filename: str) -> dict:
    collection = json.loads((_MOCKDATA / filename).read_text(encoding="utf-8"))

    def walk(items):
        for item in items:
            if "item" in item:
                found = walk(item["item"])
                if found is not None:
                    return found
                continue
            url = item.get("request", {}).get("url")
            raw = url.get("raw") if isinstance(url, dict) else url
            if raw and raw.rstrip("/").endswith("/main"):
                responses = item.get("response") or []
                if responses and responses[0].get("body"):
                    return json.loads(responses[0]["body"])
        return None

    return walk(collection.get("item", []))


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
    entry = await _setup(hass, monkeypatch, "v2",
                         _main_body("Eveus API VW.postman_collection.json"), "e_v2")
    await _assert_snapshot(hass, entry, snapshot)


async def test_snapshot_v1(hass, snapshot, freezer, monkeypatch):
    freezer.move_to(_FROZEN)
    entry = await _setup(hass, monkeypatch, "v1",
                         _main_body("Eveus API Bolt.postman_collection.json"), "e_v1")
    await _assert_snapshot(hass, entry, snapshot)
