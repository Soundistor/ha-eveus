"""A failed firmware-version read must leave a trace.

The read swallows its own error on purpose — a missing version must never break
the poll — and for that reason it used to be perfectly silent. Reproduced live
on V1 2026-09-01: zero lines in `core`, and 401, a timeout and a changed footer
were indistinguishable. Half an hour of a live-station window went into telling
them apart by hand.

These pin the trace itself. The one-shot warning and the diagnostics payload
that consume it live in tests/test_coordinator.py and tests/test_diagnostics.py.
"""
from __future__ import annotations

from charger.base import BaseCharger
from charger.v1 import ChargerV1
from charger.v2 import ChargerV2
import pytest

_FOOTER = "<html><footer>EnergyStar V5.23</footer></html>"


def _charger(page=None, exc=None) -> ChargerV1:
    charger = ChargerV1("1.2.3.4", "admin", "secret")

    async def _request_text(method, path):
        if exc is not None:
            raise exc
        return page

    charger._request_text = _request_text
    return charger


class _Status401(Exception):
    """Stands in for aiohttp's ClientResponseError, which carries `.status`."""

    status = 401


async def test_a_refused_read_records_the_status():
    charger = _charger(exc=_Status401())
    await charger.async_load_sw_version()

    assert charger.sw_version is None
    assert "401" in charger.sw_version_error
    assert "_Status401" in charger.sw_version_error


async def test_a_read_that_fails_without_a_status_still_records_the_kind():
    """A timeout has no HTTP status — that is exactly the case that was
    indistinguishable from 401 in the live incident."""
    charger = _charger(exc=TimeoutError())
    await charger.async_load_sw_version()

    assert charger.sw_version is None
    assert "TimeoutError" in charger.sw_version_error


async def test_a_changed_footer_records_a_reason_although_nothing_raised():
    """The branch the first draft of this fix missed.

    A successful GET whose page no longer matches the pattern raises nothing at
    all, so a fix that only writes the reason inside `except` would leave this
    failure exactly as invisible as it was before.
    """
    charger = _charger(page="<html><footer>Some New Name V9</footer></html>")
    await charger.async_load_sw_version()

    assert charger.sw_version is None
    assert charger.sw_version_error, "silent again — the whole point of the item"


async def test_the_page_is_never_stored_in_the_reason():
    """diagnostics carries this value into GitHub issue attachments, and the
    page the station serves holds its identifiers."""
    secret = "STATION-SENTINEL-9f3a"
    charger = _charger(page=f"<html>{secret}</html>")
    await charger.async_load_sw_version()

    assert secret not in charger.sw_version_error


async def test_a_successful_read_clears_an_earlier_reason():
    charger = _charger(page=_FOOTER)
    charger.sw_version_error = "TimeoutError"

    await charger.async_load_sw_version()

    assert charger.sw_version == "EnergyStar V5.23"
    assert charger.sw_version_error is None


@pytest.mark.parametrize("cls", [BaseCharger, ChargerV2])
async def test_a_generation_with_nothing_to_read_records_nothing(cls):
    """The base implementation is a no-op — it attempts nothing, so it has no
    failure to report. That absence is what the coordinator keys its warning
    off, instead of the attempt counter, which every V2 install runs out."""
    charger = cls("1.2.3.4")
    await charger.async_load_sw_version()

    assert charger.sw_version_error is None
