"""Fixtures for testing."""

import importlib.util
import socket
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Standalone `charger` package shim (unchanged).
#
# The transform_data / session-transition unit tests import `from charger.v1
# import ChargerV1` without pulling in homeassistant. Importing the package as
# custom_components.eveus.charger would execute eveus/__init__.py (needs HA),
# so we load the charger subpackage on its own under the top-level name
# `charger`. This must keep working alongside phacc.
# ---------------------------------------------------------------------------
_CHARGER_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "eveus" / "charger"
)

_spec = importlib.util.spec_from_file_location(
    "charger",
    _CHARGER_DIR / "__init__.py",
    submodule_search_locations=[str(_CHARGER_DIR)],
)
_pkg = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("charger", _pkg)
_spec.loader.exec_module(_pkg)


# ---------------------------------------------------------------------------
# pytest-homeassistant-custom-component (phacc) setup.
#
# phacc auto-registers as a pytest plugin via its entry point, but its
# documented setup also asks for the line below plus an autouse
# enable_custom_integrations fixture so custom components load under `hass`.
# ---------------------------------------------------------------------------
pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant discover this custom integration in tests."""
    yield


# ---------------------------------------------------------------------------
# Windows event-loop socket workaround.
#
# phacc disables sockets per test (pytest_socket) with allow_unix_socket=True.
# On POSIX the asyncio event-loop self-pipe uses an AF_UNIX socketpair, so it
# is allowed. On Windows there is no AF_UNIX socketpair: asyncio falls back to
# an AF_INET pair, which pytest_socket blocks at socket construction, so even
# creating the loop raises SocketBlockedError. Re-enabling sockets after
# phacc's setup hook restores loop creation on Windows. Guarded to win32 so CI
# (Linux) keeps phacc's network isolation intact.
# ---------------------------------------------------------------------------
if sys.platform == "win32":

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_fixture_setup(fixturedef):
        # Runs immediately around every fixture setup, including phacc's
        # event_loop. Re-enabling sockets here (after phacc's runtest_setup
        # disabled them) lets the loop's AF_INET self-pipe be created.
        import pytest_socket

        pytest_socket.enable_socket()
        yield
