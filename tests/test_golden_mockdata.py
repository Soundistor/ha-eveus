"""Golden/contract tests: real Postman /main snapshots through transform_data.

Pins the live-device contract for both firmware families so any future change
to the charger package's output (scaling, enum maps, added/dropped keys) is
caught. Loaded standalone via the conftest `charger` shim — no homeassistant.

Instead of copying ~40/~90 literal values, each expected dict is built from the
raw body with the exact fields transform_data changes overridden. That both
pins the full result AND documents precisely what the transform touches, while
staying robust to float representation (same json.loads doubles on both sides).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from charger.v1 import ChargerV1
from charger.v2 import ChargerV2

_MOCKDATA = Path(__file__).resolve().parents[1] / "mockData"


def _extract_main(filename: str) -> dict:
    """Return the saved POST /main response body from a Postman collection."""
    collection = json.loads((_MOCKDATA / filename).read_text(encoding="utf-8"))

    def walk(items):
        for item in items:
            if "item" in item:  # nested folder
                found = walk(item["item"])
                if found is not None:
                    return found
                continue
            url = item.get("request", {}).get("url")
            raw = url.get("raw") if isinstance(url, dict) else url
            if raw and raw.rstrip("/").endswith("/main"):
                responses = item.get("response") or []
                if responses and responses[0].get("body"):
                    return json.loads(responses[0]["body"])
        return None

    body = walk(collection.get("item", []))
    if body is None:
        pytest.skip(f"no saved /main response body in {filename}")
    return body


def test_golden_v1_bolt():
    raw = _extract_main("Eveus API Bolt.postman_collection.json")
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

    # V1 systemTime is time-only ("01:25:50") -> today's date, tz-aware.
    assert isinstance(out_system_time, datetime)
    assert out_system_time.tzinfo is not None
    assert (out_system_time.hour, out_system_time.minute, out_system_time.second) == (1, 25, 50)

    # Single-phase device: phase 2/3 measurements are always zero.
    assert (raw["curMeas2"], raw["curMeas3"], raw["voltMeas2"], raw["voltMeas3"]) == (0, 0, 0, 0)


def test_golden_v2_vw():
    raw = _extract_main("Eveus API VW.postman_collection.json")
    out = ChargerV2("1.2.3.4").transform_data(dict(raw))

    # V2 transform: state/subState/aiStatus -> lowercase strings, unix
    # systemTime -> UTC datetime; all other fields (already in real units)
    # pass through unchanged.
    expected = dict(raw)
    expected["state"] = "charging"
    expected["subState"] = "no_limits"
    expected["aiStatus"] = "power"
    expected["systemTime"] = datetime(2024, 12, 12, 16, 59, 21, tzinfo=timezone.utc)

    assert out == expected

    # Single-phase device: phase 2/3 measurements are always zero.
    assert (out["curMeas2"], out["curMeas3"], out["voltMeas2"], out["voltMeas3"]) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "cls,filename",
    [
        (ChargerV1, "Eveus API Bolt.postman_collection.json"),
        (ChargerV2, "Eveus API VW.postman_collection.json"),
    ],
)
def test_transform_does_not_mutate_input(cls, filename):
    raw = _extract_main(filename)
    reference = dict(raw)
    cls("1.2.3.4").transform_data(raw)
    assert raw == reference
