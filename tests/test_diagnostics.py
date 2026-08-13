"""Diagnostics must not leak device identifiers into GitHub issue attachments."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.eveus.diagnostics import async_get_config_entry_diagnostics

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v2_main.json"


# Every redacted field gets a value that cannot occur by accident in JSON, so
# "the secret is absent" is provable. Short values like "p" would pass the
# assertion trivially and prove nothing. The IP deliberately differs from the
# fixture's STA_IP_Addres: with the same string, the config-side assertion would
# be satisfied by the station-side redaction and never fail on its own.
_CONFIG_SENTINELS = {
    "ip_address": "10.99.99.99",
    "username": "USER-SENTINEL-9f3a",
    "password": "PW-SENTINEL-9f3a",
}


@pytest.fixture(name="entry")
def entry_fixture():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    # serialNumCPU is empty in the shared fixture; fill it here rather than in
    # the file, which also feeds the golden and snapshot tests.
    data["serialNumCPU"] = "CPU-SENTINEL-9f3a"
    return SimpleNamespace(
        data=dict(_CONFIG_SENTINELS),
        runtime_data=SimpleNamespace(coordinator=SimpleNamespace(data=data)),
    )


async def test_identifiers_are_redacted(entry):
    raw = entry.runtime_data.coordinator.data
    out = json.dumps(await async_get_config_entry_diagnostics(None, entry))

    for key in ("stationId", "STA_IP_Addres", "serialNum", "serialNumCPU"):
        assert str(raw[key]) not in out, f"{key} value leaked"


async def test_credentials_are_redacted(entry):
    """The password is the one value that must never reach a GitHub issue.

    Nothing used to assert it: dropping "password" from _TO_REDACT left every
    test green.
    """
    out = json.dumps(await async_get_config_entry_diagnostics(None, entry))

    for key, value in _CONFIG_SENTINELS.items():
        assert value not in out, f"{key} value leaked"


async def test_debugging_fields_survive(entry):
    out = await async_get_config_entry_diagnostics(None, entry)
    assert out["coordinator_data"]["currentSet"] == 30
    assert out["coordinator_data"]["verFWMain"] == entry.runtime_data.coordinator.data["verFWMain"]
