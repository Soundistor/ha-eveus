"""Which energy counter claims monotonicity, and which must not.

Two sensors that look identical — kWh, ENERGY, both counters — need opposite
state classes, and the reason is not symmetric:

  * totalEnergy really steps backwards. The station drops whatever it had not
    flushed to flash when it restarts (measured 2026-09-03: 78.5 -> 77.9).
    Under TOTAL_INCREASING the recorder reads that as a counter reset and adds
    the whole reading to the long-term sum — measured 2026-09-10, ~120 kWh of
    consumption that never happened.
  * IEM1/IEM2 are the user-resettable trip meters. Their reset to zero is
    exactly the case TOTAL_INCREASING exists for: it starts a new cycle and
    keeps the accumulated sum. TOTAL would subtract the whole meter instead.

So the mutation this file has to catch is not "someone flipped totalEnergy
back" but also "someone flipped all three for consistency".
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorStateClass
import pytest

from custom_components.eveus.sensor import SENSOR_DESCRIPTIONS


def _by_key(key: str):
    for description in SENSOR_DESCRIPTIONS:
        if description.key == key:
            return description
    raise AssertionError(f"no sensor description for {key!r}")


def test_total_energy_does_not_claim_monotonicity():
    assert _by_key("totalEnergy").state_class is SensorStateClass.TOTAL


@pytest.mark.parametrize("key", ["IEM1", "IEM2"])
def test_trip_meters_keep_total_increasing(key):
    # Not an oversight, and not "the one we forgot to change" — see module
    # docstring. A reset trip meter must keep its accumulated sum.
    assert _by_key(key).state_class is SensorStateClass.TOTAL_INCREASING
