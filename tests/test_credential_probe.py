"""The credential probe is a real GET / on both generations.

Every config-flow test patches `async_check_credentials`, so nothing there
notices if the method stops issuing a request — or disappears from a charger
class altogether. That gap predates V1 getting a probe of its own; this file
closes it for both generations.

Why GET /: it is the only handler on this firmware that checks HTTP Basic at
all. POST /main and POST /pageEvent answer 200 to any password, so a password
typed into the config flow is otherwise never validated by anything
(KB-01 §1.2; measured on V2 R3.05.4 2026-08-13 and on V1 EnergyStar V5.23
2026-08-18 / 2026-09-01).
"""

from charger.base import BaseCharger
from charger.v1 import ChargerV1
from charger.v2 import ChargerV2
import pytest


class _FakeResponse:
    def raise_for_status(self) -> None:
        """A 401 would raise here; these tests only pin the request itself."""

    async def text(self) -> str:
        return "<html>EnergyStar V5.23</html>"


class _FakeExchange:
    async def __aenter__(self) -> _FakeResponse:
        return _FakeResponse()

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return _FakeExchange()


@pytest.mark.parametrize("cls", [ChargerV1, ChargerV2])
async def test_probe_issues_authenticated_get_root(cls) -> None:
    charger = cls("1.2.3.4", "admin", "secret")
    session = _FakeSession()
    charger._session = session

    await charger.async_check_credentials()

    assert len(session.calls) == 1, "the probe must issue exactly one request"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "http://1.2.3.4/"
    assert kwargs["auth"] is charger.auth, "the probe is pointless without credentials"


async def test_base_default_is_a_no_op() -> None:
    """A generation whose auth path was never measured must not be probed.

    A probe that answered 401 to a VALID password would make that charger
    impossible to add at all — worse than not checking. V1 and V2 opt in by
    overriding; the default stays silent.
    """
    charger = BaseCharger("1.2.3.4", "admin", "secret")
    session = _FakeSession()
    charger._session = session

    await charger.async_check_credentials()

    assert session.calls == []
