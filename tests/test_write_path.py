"""Write path: /pageEvent answers plain text, never JSON.

Success is the body "mainPost successfully"; a refusal is plain text too and
still arrives with HTTP 200, so the body is the only thing that tells the two
apart. Before this was fixed every write raised on resp.json() *after* the
station had already applied the command.
"""

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


async def test_success_body_accepted() -> None:
    charger, _ = _charger("mainPost successfully")
    await charger.set_current(16)


async def test_success_body_tolerates_whitespace() -> None:
    charger, _ = _charger("mainPost successfully\r\n")
    await charger.set_current(16)


@pytest.mark.parametrize(
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
    charger, session = _charger("mainPost successfully")
    await charger.set_current(16)
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://1.2.3.4/pageEvent"
    assert kwargs["data"] == "currentSet=16"
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


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
