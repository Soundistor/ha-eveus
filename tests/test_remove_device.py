"""Which device row the user is allowed to delete.

The identifier scheme changed twice without migrating the registry — IP first,
then entry_id — so one station ends up owning several rows. Measured
2026-09-03: five rows for two stations, the live ones unnamed and the ones the
owner had named long dead.

Adopting an old row is not on offer: async_update_device(new_identifiers=)
raises when the target identifiers already belong to a row, which is this exact
situation, and HA cannot merge two rows. So the integration offers deletion,
and the predicate below is the whole safety argument — the live row is
undeletable by construction, not by a heuristic.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.eveus import async_remove_config_entry_device
from custom_components.eveus.const import DOMAIN

_ENTRY_ID = "01KV2DXT"


def _entry():
    return SimpleNamespace(entry_id=_ENTRY_ID)


def _device(*identifiers):
    return SimpleNamespace(identifiers=set(identifiers))


async def test_the_live_row_cannot_be_deleted():
    device = _device((DOMAIN, _ENTRY_ID))

    assert await async_remove_config_entry_device(None, _entry(), device) is False


@pytest.mark.parametrize(
    "identifier",
    [
        (DOMAIN, "192.168.31.101"),   # the pre-0.4.0 scheme
        (DOMAIN, "192.168.31.100"),
        (DOMAIN, "some-older-id"),    # the scheme before that one
    ],
)
async def test_a_row_from_an_older_scheme_can_be_deleted(identifier):
    device = _device(identifier)

    assert await async_remove_config_entry_device(None, _entry(), device) is True


async def test_a_row_that_also_carries_the_current_identifier_stays():
    # Belt and braces: a row holding both identifiers is still the live one.
    device = _device((DOMAIN, "192.168.31.101"), (DOMAIN, _ENTRY_ID))

    assert await async_remove_config_entry_device(None, _entry(), device) is False


async def test_another_entrys_row_can_be_deleted_from_this_one():
    # Two stations, two entries. HA calls this hook for every row the entry
    # owns, and a row keyed to a different entry_id is not this entry's live
    # row — deleting it here removes it from THIS entry only (the core drops
    # the config entry id, it does not destroy a row another entry still uses).
    device = _device((DOMAIN, "01OTHER"))

    assert await async_remove_config_entry_device(None, _entry(), device) is True


async def test_the_core_actually_offers_the_button(hass, monkeypatch):
    """The predicate is useless if the core never finds the hook.

    `supports_remove_device` is a hasattr check on the component module, so a
    rename or a move into a submodule silently takes the Delete button away
    again and every test above still passes.
    """
    import aiohttp
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    async def _fail(self):
        raise aiohttp.ClientConnectionError("Cannot connect to host 1.2.3.4:80")

    monkeypatch.setattr(
        "custom_components.eveus.charger.v2.ChargerV2.get_status", _fail
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "1.2.3.4",
            "model": "v2",
            "username": "admin",
            "password": "secret",
            "device_prefix": "rm",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.supports_remove_device is True
