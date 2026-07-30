"""Write path: /pageEvent answers plain text, never JSON.

On V2 success is the body "OK" (confirmed live on firmware R3.05.4,
2026-07-27); a refusal is plain text too and still arrives with HTTP 200, so
the body is the only thing that tells the two apart. Before this was fixed
every write raised on resp.json() *after* the station had already applied the
command.

V1 gives no such signal: measured on EnergyStar V5.23 (2026-07-30), an applied
write and an unknown parameter name both answer HTTP 200 / text/plain / zero
bytes. Checking the body there turned every successful V1 write into an error
toast, so V1 sets `write_ack = None` and relies on the HTTP status.
"""

from charger.v1 import ChargerV1
from charger.v2 import ChargerV2
from homeassistant.exceptions import HomeAssistantError
import pytest


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        """HTTP is always 200 here — refusals come through the body."""

    async def text(self) -> str:
        return self._body


class _FakeSession:
    """Records every request and replies with a canned body."""

    def __init__(self, body: str) -> None:
        self._body = body
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return _FakeExchange(self._body)


class _FakeExchange:
    def __init__(self, body: str) -> None:
        self._body = body

    async def __aenter__(self) -> _FakeResponse:
        return _FakeResponse(self._body)

    async def __aexit__(self, *exc_info) -> bool:
        return False


def _charger(body: str) -> tuple[ChargerV2, _FakeSession]:
    charger = ChargerV2("1.2.3.4")
    session = _FakeSession(body)
    charger._session = session
    return charger, session


def _charger_v1(body: str) -> tuple[ChargerV1, _FakeSession]:
    charger = ChargerV1("1.2.3.4")
    session = _FakeSession(body)
    charger._session = session
    return charger, session


async def test_success_body_accepted() -> None:
    charger, _ = _charger("OK")
    await charger.set_current(16)


async def test_success_body_tolerates_whitespace() -> None:
    charger, _ = _charger("OK\r\n")
    await charger.set_current(16)


@pytest.mark.parametrize(
    # Refusal bodies per static firmware analysis — not yet confirmed live,
    # unlike the "OK" success body above. Any body other than "OK" must raise
    # regardless of the exact wording.
    "body",
    ["ILLEGAL_CMD", "Failed to post control value", "content too long", ""],
)
async def test_refusal_raises(body: str) -> None:
    charger, _ = _charger(body)
    with pytest.raises(HomeAssistantError):
        await charger.set_current(16)


async def test_refusal_message_names_charger_and_body() -> None:
    charger, _ = _charger("ILLEGAL_CMD")
    with pytest.raises(HomeAssistantError) as err:
        await charger.set_current(16)
    assert "1.2.3.4" in str(err.value)
    assert "ILLEGAL_CMD" in str(err.value)


async def test_request_shape() -> None:
    charger, session = _charger("OK")
    await charger.set_current(16)
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://1.2.3.4/pageEvent"
    assert kwargs["data"] == "currentSet=16"
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


async def test_v1_has_no_charge_switch_capability() -> None:
    """No switch entity is created for V1 — see switch.async_setup_entry."""
    from charger.v2 import ChargerV2 as _V2

    assert "charge_switch" not in ChargerV1("1.2.3.4").capabilities
    assert "charge_switch" in _V2("1.2.3.4").capabilities


async def test_v1_turn_off_raises_before_any_request() -> None:
    """Guard on the charger API itself, so no future caller can revive the no-op."""
    charger, session = _charger_v1("")
    with pytest.raises(HomeAssistantError) as err:
        await charger.set_enabled(False)
    assert not session.calls, "nothing may be sent for an impossible command"
    assert "1.2.3.4" in str(err.value)


async def test_v1_turn_on_still_works() -> None:
    charger, session = _charger_v1("")
    await charger.set_enabled(True)
    assert session.calls[0][2]["data"] == "evseEnabled=1"


async def test_v2_turn_off_is_untouched() -> None:
    charger, session = _charger("OK")
    await charger.set_enabled(False)
    assert session.calls, "V2 can be stopped remotely"


@pytest.mark.parametrize("value", [-1, 256, 999])
async def test_out_of_range_current_raises_and_sends_nothing(value: int) -> None:
    """The station wraps to uint8_t instead of refusing — catch it client-side."""
    charger, session = _charger("OK")
    with pytest.raises(HomeAssistantError):
        await charger.set_current(value)
    assert not session.calls


async def test_in_range_current_is_unchanged() -> None:
    charger, session = _charger("OK")
    await charger.set_current(12)
    assert session.calls[0][2]["data"] == "currentSet=12"


async def test_ai_mode_body_is_the_parameter_alone() -> None:
    """No `pageevent=` prefix: the station matches names in the body itself."""
    charger, session = _charger("OK")
    await charger.set_ai_mode(3)
    assert session.calls[0][2]["data"] == "aiMode=3"


async def test_v1_empty_body_is_not_a_refusal() -> None:
    """V1's applied writes answer with an empty body — that must not raise."""
    charger, session = _charger_v1("")
    await charger.set_current(16)
    assert session.calls, "the write must still be sent"


async def test_v1_accepts_any_body_including_v2_ack() -> None:
    charger, _ = _charger_v1("OK")
    await charger.set_enabled(True)


async def test_v2_empty_body_still_raises() -> None:
    """The V1 relaxation must not weaken V2, where an empty body means failure."""
    charger, _ = _charger("")
    with pytest.raises(HomeAssistantError):
        await charger.set_current(16)


async def test_unstudied_generation_defaults_to_the_v2_contract() -> None:
    """A new charger class inherits write_ack='OK' — fail loudly, not silently."""
    from charger.base import BaseCharger

    assert BaseCharger.write_ack == "OK"
    assert ChargerV1.write_ack is None


async def test_every_write_path_validates_the_body() -> None:
    """set_enabled / set_ai_mode / sync_time all go through _post_page_event."""
    for write in (
        lambda c: c.set_enabled(True),
        lambda c: c.set_ai_mode(1),
        lambda c: c.sync_time(),
    ):
        charger, _ = _charger("ILLEGAL_CMD")
        with pytest.raises(HomeAssistantError):
            await write(charger)


async def test_v1_sync_time_writes_local_wall_clock(monkeypatch) -> None:
    """V1 renders the epoch it is given as-is, so send local, not UTC.

    Measured 2026-07-30: a UTC epoch made the station display UTC while its own
    timeZone field said 2.
    """
    from datetime import UTC, datetime, timedelta, timezone

    tz = timezone(timedelta(hours=3))
    moment = datetime(2026, 7, 30, 18, 59, 39, tzinfo=tz)
    monkeypatch.setattr("homeassistant.util.dt.now", lambda: moment)

    charger, session = _charger_v1("")
    await charger.sync_time()

    sent = int(session.calls[0][2]["data"].split("=")[1])
    # Reading the number back as a UTC wall clock must give the local time.
    assert datetime.fromtimestamp(sent, tz=UTC).strftime("%H:%M:%S") == "18:59:39"


async def test_v1_advertises_sync_time() -> None:
    assert "sync_time" in ChargerV1("1.2.3.4").capabilities
