"""Fixtures for testing."""

import importlib.util
import sys
from pathlib import Path

_CHARGER_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "eveus" / "charger"
)

# Load the charger package standalone: importing it as
# custom_components.eveus.charger would execute eveus/__init__.py,
# which requires homeassistant — not needed for these unit tests.
_spec = importlib.util.spec_from_file_location(
    "charger",
    _CHARGER_DIR / "__init__.py",
    submodule_search_locations=[str(_CHARGER_DIR)],
)
_pkg = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("charger", _pkg)
_spec.loader.exec_module(_pkg)
