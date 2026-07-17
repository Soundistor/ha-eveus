"""Golden/contract tests: sanitized /main fixtures through transform_data.

Pins the live-device contract for both firmware families so any future change
to the charger package's output (scaling, enum maps, added/dropped keys) is
caught. Loaded standalone via the conftest `charger` shim — no homeassistant.

The /main bodies live in tests/fixtures/{v1,v2}_main.json — committed,
device-identifiers scrubbed (serialNum/stationId/IP), every contract-relevant
numeric/state value preserved verbatim — so the golden tests run in CI too. Each
expected dict is built from the raw body with the exact fields transform_data
changes overridden, so the assertion pins the full result while staying robust
to float representation.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from charger.v1 import ChargerV1
from charger.v2 import ChargerV2
import pytest

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _body(family: str) -> dict:
    return json.loads((_FIXTURES / f"{family}_main.json").read_text(encoding="utf-8"))


def test_golden_v1():
    raw = _body("v1")
    out = ChargerV1("1.2.3.4").transform_data(dict(raw))

    # V1 transform: state/aiStatus -> lowercase strings, current/energy scaled
    # by 0.1, computed powerMeas added, systemTime parsed to a datetime; every
    # other field passes through unchanged.
    expected = dict(raw)
    expected["state"] = "charging"
    expected["aiStatus"] = "off"
    expected["curMeas1"] = 23.8       # 238 * 0.1
    expected["sessionEnergy"] = 6.3   # 63 * 0.1
    expected["totalEnergy"] = 1162.0  # 11620 * 0.1
    expected["powerMeas"] = 5045.6    # voltMeas1(212) * raw curMeas1(238) * 0.1
    del expected["systemTime"]

    out_system_time = out.pop("systemTime")
    assert out == expected

    # V1 systemTime is time-only ("01:25:50") -> naive datetime (today's date);
    # the coordinator localizes it to HA's timezone, so charger output is naive.
    assert isinstance(out_system_time, datetime)
    assert out_system_time.tzinfo is None
    assert (out_system_time.hour, out_system_time.minute, out_system_time.second) == (1, 25, 50)

    # Single-phase device: phase 2/3 measurements are always zero.
    assert (raw["curMeas2"], raw["curMeas3"], raw["voltMeas2"], raw["voltMeas3"]) == (0, 0, 0, 0)


def test_golden_v2():
    raw = _body("v2")
    out = ChargerV2("1.2.3.4").transform_data(dict(raw))

    # V2 transform: state/subState/aiStatus -> lowercase strings, unix
    # systemTime -> UTC datetime; all other fields (already in real units)
    # pass through unchanged.
    expected = dict(raw)
    expected["state"] = "charging"
    expected["subState"] = "no_limits"
    expected["aiStatus"] = "power"
    expected["systemTime"] = datetime(2024, 12, 12, 16, 59, 21, tzinfo=UTC)

    assert out == expected

    # Single-phase device: phase 2/3 measurements are always zero.
    assert (out["curMeas2"], out["curMeas3"], out["voltMeas2"], out["voltMeas3"]) == (0, 0, 0, 0)


@pytest.mark.parametrize("family,cls", [("v1", ChargerV1), ("v2", ChargerV2)])
def test_transform_does_not_mutate_input(family, cls):
    raw = _body(family)
    reference = dict(raw)
    cls("1.2.3.4").transform_data(raw)
    assert raw == reference
