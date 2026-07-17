"""Config flow tests: user, reconfigure, reauth + error branches.

The flow's _test_connection builds a real ChargerV1/V2 and calls get_status;
tests patch get_status on both charger classes to succeed or raise, exercising
the flow branching AND _test_connection's 401-vs-other mapping.
"""
from __future__ import annotations

import asyncio

import aiohttp
import pytest
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


def _patch_status(monkeypatch, *, exc=None):
    async def _fake(self):
        if exc is not None:
            raise exc
        return {"state": 2}

    monkeypatch.setattr("custom_components.eveus.charger.v2.ChargerV2.get_status", _fake)
    monkeypatch.setattr("custom_components.eveus.charger.v1.ChargerV1.get_status", _fake)


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


async def test_user_cannot_connect(hass, monkeypatch):
    _patch_status(monkeypatch, exc=aiohttp.ClientConnectionError("down"))
    result = await _start_user(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input())
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


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
