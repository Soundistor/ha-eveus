"""Diagnostics must not leak device identifiers into GitHub issue attachments."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.eveus.diagnostics import async_get_config_entry_diagnostics

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v2_main.json"


@pytest.fixture(name="entry")
def entry_fixture():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return SimpleNamespace(
        data={"ip_address": "192.168.1.100", "username": "u", "password": "p"},
        runtime_data=SimpleNamespace(coordinator=SimpleNamespace(data=data)),
    )


async def test_identifiers_are_redacted(entry):
    raw = entry.runtime_data.coordinator.data
    out = json.dumps(await async_get_config_entry_diagnostics(None, entry))

    # serialNumCPU is empty in the fixture, so there is no value to look for.
    for key in ("stationId", "STA_IP_Addres", "serialNum"):
        assert str(raw[key]) not in out, f"{key} value leaked"


async def test_debugging_fields_survive(entry):
    out = await async_get_config_entry_diagnostics(None, entry)
    assert out["coordinator_data"]["currentSet"] == 30
    assert out["coordinator_data"]["verFWMain"] == entry.runtime_data.coordinator.data["verFWMain"]
