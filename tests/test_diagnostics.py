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
    coordinator = SimpleNamespace(
        data=data,
        charger=SimpleNamespace(
            sw_version=None,
            sw_version_error="ClientResponseError (HTTP 401)",
        ),
        _sw_version_attempts=3,
        _sw_version_loaded=True,
    )
    return SimpleNamespace(
        data=dict(_CONFIG_SENTINELS),
        runtime_data=SimpleNamespace(coordinator=coordinator),
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


async def test_why_the_version_read_failed_is_recoverable(entry):
    """Diagnostics is the route the 2026-09-01 incident was actually solved by.

    The read swallows its own failure so it cannot break the poll, so this is
    the only place the cause survives. The attempt count is what separates one
    transient miss from "gave up".
    """
    out = await async_get_config_entry_diagnostics(None, entry)

    assert out["sw_version"]["error"] == "ClientResponseError (HTTP 401)"
    assert out["sw_version"]["attempts"] == 3
    assert out["sw_version"]["gave_up"] is True
