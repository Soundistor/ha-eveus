"""Golden/contract tests: real Postman /main snapshots through transform_data.

Pins the live-device contract for both firmware families so any future change
to the charger package's output (scaling, enum maps, added/dropped keys) is
caught. Loaded standalone via the conftest `charger` shim — no homeassistant.

The Postman collections are discovered by globbing mockData/ and classified by
payload content (V2 carries subState/verFWMain, V1 does not) — no snapshot
filenames are hard-coded. Each expected dict is built from the raw body with the
exact fields transform_data changes overridden, so the assertion pins the full
result while staying robust to float representation.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from charger.v1 import ChargerV1
from charger.v2 import ChargerV2
import pytest

_MOCKDATA = Path(__file__).resolve().parents[1] / "mockData"


def _extract_main(path: Path) -> dict | None:
    """Return the saved POST /main response body from a Postman collection."""
    collection = json.loads(path.read_text(encoding="utf-8"))

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

    return walk(collection.get("item", []))


def _main_bodies() -> dict[str, dict]:
    """Discover /main bodies from mockData, keyed by firmware family (v1/v2)."""
    bodies: dict[str, dict] = {}
    for path in sorted(_MOCKDATA.glob("*.postman_collection.json")):
        body = _extract_main(path)
        if body is None:
            continue
        family = "v2" if ("subState" in body or "verFWMain" in body) else "v1"
        bodies[family] = body
    return bodies


def _body(family: str) -> dict:
    body = _main_bodies().get(family)
    if body is None:
        pytest.skip(f"no {family} /main snapshot in mockData")
    return body


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

    # V1 systemTime is time-only ("01:25:50") -> today's date, tz-aware.
    assert isinstance(out_system_time, datetime)
    assert out_system_time.tzinfo is not None
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
