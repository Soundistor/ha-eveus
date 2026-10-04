"""The session-reset identity, replayed against counters the station produced.

Across a session reset the two counters disagree by exactly the finished
session's energy:

    D = (totalEnergy - totalEnergy0) - (sessionEnergy - sessionEnergy0)

Within one session they move in lockstep, so D stays at the measurement floor.
That is the whole mechanism, and it is why no gap gate is needed.

Why the data comes from a capture rather than from values written here: the
rule's entire claim is about how a particular firmware moves two counters, and
a test that invents the numbers proves only that the arithmetic in the sensor
matches the arithmetic in the test. These frames were captured on 2026-09-27
while the cable was unplugged and replugged twice (fixtures/session_reset_v*.json,
lifted from a gitignored dense log so CI can see them). A gap in the observer is
carved out of a dense capture after the fact, which is what lets one window
answer for every gap length at once.
"""
from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path

from homeassistant.util import dt as dt_util
import pytest

from custom_components.eveus.sensor import (
    _CHARGE_MOVED_KWH,
    _SESSION_ENERGY_DESCRIPTION,
    SessionEnergySensor,
)

_FIXTURES = Path(__file__).parent / "fixtures"


class _Coord:
    def __init__(self):
        self.data: dict = {}
        self.last_update_success = True
        self.gap_s: float | None = 30.0
        self.frame_time = None

    def async_add_listener(self, update_callback, context=None):
        return lambda: None


class _Charger:
    ip = "1.2.3.4"
    model_name = "Test"
    capabilities: set = set()


@pytest.fixture(autouse=True)
def strictly_increasing_clock(monkeypatch):
    """Every fire must get a distinguishable stamp.

    Counting "did last_reset change" is the only way to see a fire from
    outside, and on this host dt_util.utcnow() has about 15 ms of granularity
    — a whole replay loop fits inside one tick, so repeated fires all stamped
    the same value and read as one. That hid a mutation completely: removing
    the re-anchoring fires on EVERY following frame, 84 of them in this
    capture, and the test still passed.
    """
    import custom_components.eveus.sensor as sensor_mod

    tick = [dt_util.utcnow()]

    def _utcnow():
        tick[0] += timedelta(seconds=1)
        return tick[0]

    monkeypatch.setattr(sensor_mod.dt_util, "utcnow", _utcnow)


def _load(name: str) -> list[dict]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["frames"]


def _segments(frames: list[dict]) -> list[list[dict]]:
    """Split the capture where sessionEnergy falls — a session boundary."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    for f in frames:
        if cur and f["sessionEnergy"] < cur[-1]["sessionEnergy"]:
            out.append(cur)
            cur = []
        cur.append(f)
    if cur:
        out.append(cur)
    return out


def _sensor():
    coord = _Coord()
    s = SessionEnergySensor(coord, _Charger(), _SESSION_ENERGY_DESCRIPTION, "smoke", "e1")
    s.async_write_ha_state = lambda: None
    return s, coord


def _feed(sensor, coord, frame: dict) -> None:
    coord.data = {
        "sessionEnergy": frame["sessionEnergy"],
        "totalEnergy": frame["totalEnergy"],
    }
    sensor._handle_coordinator_update()


def _replay_pair(pre: dict, post: dict) -> bool:
    """Observer sees `pre`, goes blind, comes back to `post`. Did it fire?

    The sensor is fed `pre` twice: the first frame only takes the anchor, since
    there is nothing to compare against yet. Returns whether last_reset moved
    on `post`.
    """
    sensor, coord = _sensor()
    _feed(sensor, coord, pre)
    before = sensor._attr_last_reset
    _feed(sensor, coord, post)
    return sensor._attr_last_reset != before


@pytest.fixture(params=["session_reset_v1.json", "session_reset_v2.json"])
def capture(request):
    frames = _load(request.param)
    segs = _segments(frames)
    assert len(segs) == 3, f"{request.param}: expected three sessions, got {len(segs)}"
    return request.param, segs


def test_within_a_session_the_identity_never_fires(capture):
    """Every ordered pair inside one session: silence.

    This is the false-positive floor, and it is the measurement that matters
    most — a false last_reset writes the live session's energy into long-term
    statistics as a phantom.
    """
    name, segs = capture
    pairs = 0
    for seg in segs:
        for i in range(len(seg)):
            for j in range(i + 1, len(seg)):
                assert not _replay_pair(seg[i], seg[j]), (
                    f"{name}: fired inside one session, frames {seg[i]['t']} -> "
                    f"{seg[j]['t']} ({seg[i]['sessionEnergy']} -> "
                    f"{seg[j]['sessionEnergy']} kWh)"
                )
                pairs += 1
    expected = {"session_reset_v1.json": 15743, "session_reset_v2.json": 8357}[name]
    assert pairs == expected, (
        "the pair count pins which definition of 'within a session' is being "
        "swept, so a later reading of the criterion cannot drift to 'adjacent "
        "frames' (about 205) without the test saying so"
    )


def test_across_a_session_boundary_it_always_fires(capture):
    """Every ordered pair spanning a reset: exactly one move of last_reset."""
    name, segs = capture
    pairs = 0
    for a in range(len(segs)):
        for b in range(a + 1, len(segs)):
            for pre in segs[a]:
                for post in segs[b]:
                    assert _replay_pair(pre, post), (
                        f"{name}: missed a reset, frames {pre['t']} -> {post['t']}"
                    )
                    pairs += 1
    assert pairs > 7000, f"{name}: only {pairs} cross-session pairs swept"


def test_the_pairs_the_old_rule_cannot_see_are_the_point(capture):
    """The subset where the new session had already outgrown the old one.

    `current < prev` is silent on these by construction, so if the identity
    did not fire the reset would be invisible to every rule there is. This is
    the defect the item exists to fix, and it has to be swept separately —
    the previous test passes even if the old rule is doing all the work.
    """
    name, segs = capture
    blind = 0
    for a in range(len(segs)):
        for b in range(a + 1, len(segs)):
            for pre in segs[a]:
                for post in segs[b]:
                    if post["sessionEnergy"] < pre["sessionEnergy"]:
                        continue  # the observed-drop rule covers this one
                    assert _replay_pair(pre, post), (
                        f"{name}: a reset no rule can see, frames "
                        f"{pre['t']} -> {post['t']}"
                    )
                    blind += 1
    assert blind > 0, f"{name}: the capture holds no pairs that blind the old rule"


def test_a_frame_without_the_lifetime_counter_clears_the_anchor():
    """Half a pair is worse than none, so the anchor is dropped, not kept.

    Asserting only that last_reset stayed put would pass with the clearing
    removed — inside a session D is ~0 either way — so this looks at the
    anchor itself.
    """
    frames = _load("session_reset_v2.json")
    sensor, coord = _sensor()

    _feed(sensor, coord, frames[0])
    assert sensor._anchor_total is not None

    coord.data = {"sessionEnergy": frames[1]["sessionEnergy"]}  # guard stripped it
    sensor._handle_coordinator_update()
    assert sensor._anchor_energy is None and sensor._anchor_total is None

    _feed(sensor, coord, frames[2])
    assert sensor._anchor_total == frames[2]["totalEnergy"], "re-anchored silently"
    assert sensor._attr_last_reset is None


def test_an_all_zero_v1_frame_is_not_an_anchor():
    """V1 serves every field as zero for ~8 s after a reboot.

    Anchoring on it makes the next frame read as a 200 kWh session boundary.
    Found in two retained logs while sweeping, not reasoned about: it is the
    `state=0(no_data)` frame.
    """
    sensor, coord = _sensor()

    _feed(sensor, coord, {"t": "0", "sessionEnergy": 0.0, "totalEnergy": 0.0})
    assert sensor._anchor_total is None, "an all-zero frame carries no counter"

    _feed(sensor, coord, {"t": "1", "sessionEnergy": 0.0, "totalEnergy": 218.6})
    assert sensor._attr_last_reset is None, (
        "a reboot must not be read as a 218 kWh session ending"
    )


def test_the_anchor_survives_a_restart_as_stored_values():
    """The whole point of persisting it: the reset happens while HA is down."""
    frames = _load("session_reset_v2.json")
    segs = _segments(frames)
    sensor, coord = _sensor()

    _feed(sensor, coord, segs[1][-1])          # last frame before HA stops
    stored = sensor.extra_restore_state_data.as_dict()
    assert stored["anchor_total"] is not None

    revived, coord2 = _sensor()
    revived._anchor_energy = stored["anchor_energy"]
    revived._anchor_total = stored["anchor_total"]

    _feed(revived, coord2, segs[2][-1])        # first frame after HA is back
    assert revived._attr_last_reset is not None, (
        "without the persisted anchor there is nothing to compare against, "
        "which is the failure two earlier drafts of this item shipped"
    )


def test_one_boundary_fires_once_not_twice(capture):
    """Both rules on consecutive frames would bill the interval twice.

    The observed drop fires on the zeroing frame; without re-anchoring in that
    same frame, the next frame computes the full identity against the
    pre-reset anchor and moves last_reset again.
    """
    name, segs = capture
    sensor, coord = _sensor()
    moves = []
    # The SECOND boundary on purpose: the first session in these captures moved
    # less than the threshold, so a stale anchor across it produces a D too
    # small to fire and the test would pass with the re-anchoring removed.
    for frame in [*segs[1], *segs[2]]:
        before = sensor._attr_last_reset
        _feed(sensor, coord, frame)
        if sensor._attr_last_reset != before:
            moves.append(frame["t"])
    assert len(moves) == 1, f"{name}: last_reset moved at {moves}, expected one boundary"


def test_the_threshold_stays_below_the_v1_quantum():
    """A V1 reset of the smallest possible session shows up as exactly 0.1."""
    assert _CHARGE_MOVED_KWH < 0.1


def test_a_moved_last_reset_is_a_real_datetime():
    frames = _load("session_reset_v2.json")
    segs = _segments(frames)
    sensor, coord = _sensor()
    _feed(sensor, coord, segs[0][-1])
    _feed(sensor, coord, segs[1][-1])
    assert isinstance(sensor._attr_last_reset, type(dt_util.utcnow()))
