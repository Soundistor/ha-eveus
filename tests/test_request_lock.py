"""Every exchange with the station must be serialized.

The charger serves exactly one connection: a second one closes the first, so
a poll overlapping a write is not merely slow, it breaks both. Reads and
writes therefore share a single lock.
"""

import asyncio

from charger.v2 import ChargerV2
import pytest


class _FakeResponse:
    def __init__(self, log: list[str], tag: str, body: str) -> None:
        self._log = log
        self._tag = tag
        self._body = body

    def raise_for_status(self) -> None:
        """Always 200."""

    async def _yield_to_the_loop(self) -> None:
        # Give any concurrent task a chance to interleave — if the lock were
        # missing, this is where the second exchange would slip in.
        await asyncio.sleep(0)

    async def json(self) -> dict:
        await self._yield_to_the_loop()
        return {"state": 2}

    async def text(self) -> str:
        await self._yield_to_the_loop()
        return self._body


class _FakeExchange:
    def __init__(self, log: list[str], tag: str, body: str) -> None:
        self._log = log
        self._tag = tag
        self._body = body

    async def __aenter__(self) -> _FakeResponse:
        self._log.append(f"enter:{self._tag}")
        await asyncio.sleep(0)
        return _FakeResponse(self._log, self._tag, self._body)

    async def __aexit__(self, *exc_info) -> bool:
        self._log.append(f"exit:{self._tag}")
        return False


class _RecordingSession:
    """Logs enter/exit of every exchange so overlap is visible."""

    def __init__(self) -> None:
        self.log: list[str] = []

    def request(self, method: str, url: str, **kwargs):
        tag = url.rsplit("/", 1)[-1]
        return _FakeExchange(self.log, tag, "OK")


def _assert_never_overlapping(log: list[str]) -> None:
    """Each enter must be followed by its own exit before the next enter."""
    depth = 0
    for entry in log:
        depth += 1 if entry.startswith("enter:") else -1
        assert depth in (0, 1), f"overlapping exchanges: {log}"
    assert depth == 0


async def test_poll_and_write_do_not_overlap() -> None:
    charger = ChargerV2("1.2.3.4")
    session = _RecordingSession()
    charger._session = session

    await asyncio.gather(charger.get_status(), charger.set_current(16))

    _assert_never_overlapping(session.log)
    assert len(session.log) == 4


async def test_concurrent_writes_do_not_overlap() -> None:
    charger = ChargerV2("1.2.3.4")
    session = _RecordingSession()
    charger._session = session

    await asyncio.gather(
        charger.set_current(10),
        charger.set_enabled(True),
        charger.set_ai_mode(1),
    )

    _assert_never_overlapping(session.log)
    assert len(session.log) == 6


async def test_lock_is_released_after_a_failed_request() -> None:
    """A raising exchange must not leave the charger permanently locked."""

    class _Boom(_FakeExchange):
        async def __aenter__(self):
            raise ConnectionResetError("station dropped the session")

    class _FailingOnceSession(_RecordingSession):
        def __init__(self) -> None:
            super().__init__()
            self.first = True

        def request(self, method: str, url: str, **kwargs):
            if self.first:
                self.first = False
                return _Boom(self.log, "boom", "")
            return super().request(method, url, **kwargs)

    charger = ChargerV2("1.2.3.4")
    charger._session = _FailingOnceSession()

    with pytest.raises(ConnectionResetError):
        await charger.get_status()

    assert not charger._lock.locked()
    await charger.get_status()
