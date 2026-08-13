"""Config flow tests: user, reconfigure, reauth + error branches.

The flow's _test_connection builds a real ChargerV1/V2 and calls get_status;
tests patch get_status on both charger classes to succeed or raise, exercising
the flow branching AND _test_connection's 401-vs-other mapping.
"""
from __future__ import annotations

import aiohttp
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eveus.const import (
    CONF_DEVICE_PREFIX,
    CONF_IP_ADDRESS,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)

# The API generation is read off the payload: only V2 reports verFWWifi.
_V2_PAYLOAD = {"state": 2, "verFWWifi": "1PGRW001A-R3.02.9"}
_V1_PAYLOAD = {"state": 2}


def _patch_status(monkeypatch, *, exc=None, payload=None):
    async def _fake(self):
        if exc is not None:
            raise exc
        return dict(_V2_PAYLOAD if payload is None else payload)

    monkeypatch.setattr("custom_components.eveus.charger.v2.ChargerV2.get_status", _fake)
    monkeypatch.setattr("custom_components.eveus.charger.v1.ChargerV1.get_status", _fake)

    # A finished flow creates the entry, which HA then sets up — and setup asks
    # V1 for its firmware version over HTTP (V1 reports none in /main). Stub it
    # out: this file tests the flow, not that request.
    async def _no_version(self):
        return None

    monkeypatch.setattr(
        "custom_components.eveus.charger.v1.ChargerV1.async_load_sw_version", _no_version
    )

    # V2 credentials are probed with a second request (GET /) — stubbed here for
    # the same reason: this file tests the flow, not the request. The probe's own
    # behaviour is covered by test_user_invalid_auth_only_main_accepts_anything.
    async def _credentials_ok(self):
        return None

    monkeypatch.setattr(
        "custom_components.eveus.charger.v2.ChargerV2.async_check_credentials",
        _credentials_ok,
    )


def _user_input(ip="1.2.3.4", model="v2", prefix=""):
    return {
        CONF_IP_ADDRESS: ip,
        CONF_MODEL: model,
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "secret",
        CONF_DEVICE_PREFIX: prefix,
    }


async def _start_user(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


# --------------------------------------------------------------------------- #
# user step
# --------------------------------------------------------------------------- #

async def test_user_happy_path(hass, monkeypatch):
    _patch_status(monkeypatch)
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(prefix="garage")
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Eveus 1.2.3.4"
    assert result["data"][CONF_MODEL] == "v2"
    assert result["data"][CONF_DEVICE_PREFIX] == "garage"
    assert result["result"].unique_id == "1.2.3.4"


async def test_user_invalid_auth(hass, monkeypatch):
    _patch_status(monkeypatch, exc=aiohttp.ClientResponseError(_req(), (), status=401))
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input())
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_invalid_auth_only_main_accepts_anything(hass, monkeypatch):
    """A wrong password must be caught even though /main answers 200 to it.

    POST handlers on this hardware check no auth at all (KB-01 §1.2), so the
    payload alone made every password look valid. The flow now probes the one
    handler that does check — a V2 station whose GET / answers 401.
    """
    _patch_status(monkeypatch)                      # /main happily returns a V2 payload

    async def _rejects(self):
        raise aiohttp.ClientResponseError(_req(), (), status=401)

    monkeypatch.setattr(
        "custom_components.eveus.charger.v2.ChargerV2.async_check_credentials", _rejects
    )

    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input())

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_v1_payload_is_not_credential_probed(hass, monkeypatch):
    """V1 was never measured this way — probing it could make it unaddable.

    A probe that answered 401 to a valid password would block adding the station
    entirely, which is worse than not checking it.
    """
    _patch_status(monkeypatch, payload=_V1_PAYLOAD)
    probed = []

    async def _rejects(self):
        probed.append(1)
        raise aiohttp.ClientResponseError(_req(), (), status=401)

    monkeypatch.setattr(
        "custom_components.eveus.charger.v2.ChargerV2.async_check_credentials", _rejects
    )

    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(model="v1")
    )

    assert not probed, "a V1 payload must not be credential-probed"
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_user_cannot_connect(hass, monkeypatch):
    _patch_status(monkeypatch, exc=aiohttp.ClientConnectionError("down"))
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input())
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_v1_happy_path(hass, monkeypatch):
    _patch_status(monkeypatch, payload=_V1_PAYLOAD)
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(model="v1")
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODEL] == "v1"


async def test_user_v1_device_with_v2_selected(hass, monkeypatch):
    _patch_status(monkeypatch, payload=_V1_PAYLOAD)
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(model="v2")
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "model_mismatch"}


async def test_user_v2_device_with_v1_selected(hass, monkeypatch):
    _patch_status(monkeypatch, payload=_V2_PAYLOAD)
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(model="v1")
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "model_mismatch"}


async def test_user_prefix_taken(hass, monkeypatch):
    MockConfigEntry(
        domain=DOMAIN, unique_id="9.9.9.9", data=_user_input(ip="9.9.9.9", prefix="home")
    ).add_to_hass(hass)
    _patch_status(monkeypatch)  # would succeed, but prefix check short-circuits first
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(prefix="home")
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_DEVICE_PREFIX: "prefix_taken"}


async def test_user_duplicate_ip_aborts(hass, monkeypatch):
    MockConfigEntry(domain=DOMAIN, unique_id="1.2.3.4", data=_user_input()).add_to_hass(hass)
    _patch_status(monkeypatch)
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input())
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --------------------------------------------------------------------------- #
# reconfigure
# --------------------------------------------------------------------------- #

async def test_reconfigure_success(hass, monkeypatch):
    _patch_status(monkeypatch)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1.2.3.4", data=_user_input())
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_IP_ADDRESS: "5.5.5.5", CONF_MODEL: "v2", CONF_USERNAME: "admin", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_IP_ADDRESS] == "5.5.5.5"


async def test_reconfigure_duplicate_ip(hass, monkeypatch):
    _patch_status(monkeypatch)
    MockConfigEntry(domain=DOMAIN, unique_id="9.9.9.9", data=_user_input(ip="9.9.9.9")).add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1.2.3.4", data=_user_input())
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_IP_ADDRESS: "9.9.9.9", CONF_MODEL: "v2", CONF_USERNAME: "admin", CONF_PASSWORD: "secret"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}


async def test_reconfigure_model_mismatch(hass, monkeypatch):
    _patch_status(monkeypatch, payload=_V2_PAYLOAD)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1.2.3.4", data=_user_input())
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_IP_ADDRESS: "1.2.3.4", CONF_MODEL: "v1", CONF_USERNAME: "admin",
         CONF_PASSWORD: "secret"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "model_mismatch"}
    assert entry.data[CONF_MODEL] == "v2"   # unchanged


# --------------------------------------------------------------------------- #
# reauth
# --------------------------------------------------------------------------- #

async def test_reauth_success(hass, monkeypatch):
    _patch_status(monkeypatch)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1.2.3.4", data=_user_input())
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "newpass"}
    )
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "newpass"


async def test_reauth_invalid_auth(hass, monkeypatch):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1.2.3.4", data=_user_input())
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    _patch_status(monkeypatch, exc=aiohttp.ClientResponseError(_req(), (), status=401))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "wrong"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


def _req():
    from unittest.mock import Mock

    return Mock()
