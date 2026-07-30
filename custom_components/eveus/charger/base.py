"""Базовый класс для всех зарядок."""
from __future__ import annotations

import asyncio

import aiohttp

_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_TIMEOUT = aiohttp.ClientTimeout(total=10)

# The body /pageEvent returns when a write was applied. Confirmed live on
# firmware R3.05.4 (2026-07-27): every accepted write — currentSet, evseEnabled,
# aiMode — answers "OK". (Static firmware analysis had suggested
# "mainPost successfully"; that did not match the live device and made every
# accepted write look rejected — trust the live capture over the disassembly.)
# V1 answers differently and cannot be checked this way at all — see
# BaseCharger.write_ack.
_WRITE_OK = "OK"

AI_MODE_MAP = {0: "off", 1: "voltage", 2: "tesla_auto", 3: "power"}

# Below this the reading is the firmware's "sensor absent" sentinel (the
# station's own UI shows N/A), not a measurement — typically -60.
_TEMP_ABSENT_BELOW = -50


def blank_absent_temperature(value):
    """Return None for the 'no sensor' sentinel, the value itself otherwise."""
    try:
        return None if float(value) < _TEMP_ABSENT_BELOW else value
    except (ValueError, TypeError):
        return value


class BaseCharger:
    """Общая часть: запросы через общую сессию HA, базовый интерфейс.

    Сессию отдаёт Home Assistant (`async_get_clientsession`) — интеграция её не
    создаёт и не закрывает. `hass` необязателен: юнит-тесты `transform_data`
    инстанцируют зарядку без него и не делают сетевых запросов.
    """

    # Body a station returns when it applied a write, or None if this generation
    # gives no acknowledgement at all. Defaults to the V2 contract so a new,
    # unstudied generation fails loudly instead of silently skipping the check.
    write_ack: str | None = _WRITE_OK

    def __init__(self, ip: str, username: str | None = None,
                 password: str | None = None, hass=None) -> None:
        self.ip = ip
        self.auth = aiohttp.BasicAuth(username, password or "") if username else None
        self._hass = hass
        self._session: aiohttp.ClientSession | None = None
        # The station serves exactly ONE connection: a second one does not get
        # queued or refused, it CLOSES the existing session (seen client-side as
        # a sudden FIN/RST — ServerDisconnectedError, ConnectionResetError or a
        # truncated body). Every exchange with the device goes through this lock
        # so a write never overlaps a poll or another write.
        self._lock = asyncio.Lock()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            # Lazy import: keeps the module importable without homeassistant
            # (the charger package is loaded standalone in unit tests).
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            self._session = async_get_clientsession(self._hass)
        return self._session

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"http://{self.ip}{path}"
        async with self._lock, self._get_session().request(
            method, url, auth=self.auth, timeout=_TIMEOUT, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _request_text(self, method: str, path: str, **kwargs) -> str:
        url = f"http://{self.ip}{path}"
        async with self._lock, self._get_session().request(
            method, url, auth=self.auth, timeout=_TIMEOUT, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def _post_page_event(self, data: str) -> None:
        """Write one parameter and verify the station accepted it.

        /pageEvent never answers JSON: on V2 success is the plain text "OK" and
        a refusal is plain text too (ILLEGAL_CMD, "Failed to post control
        value", "content too long") — always with HTTP 200, so the body is the
        only signal we get. Generations that give no such signal set
        `write_ack = None` and are verified by HTTP status alone.
        """
        body = await self._request_text(
            "POST", "/pageEvent", data=data, headers=_FORM_HEADERS
        )
        if self.write_ack is not None and body.strip() != self.write_ack:
            # Lazy import: see _get_session.
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(
                f"Charger {self.ip} rejected '{data}': {body.strip()[:200]}"
            )

    async def get_status(self) -> dict:
        return await self._request("POST", "/main")

    async def set_current(self, value: int) -> None:
        await self._post_page_event(f"currentSet={value:02d}")

    async def set_ai_mode(self, mode: int) -> None:
        await self._post_page_event(f"pageevent=evseEnabled&aiMode={mode}")

    async def set_enabled(self, enabled: bool) -> None:
        raise NotImplementedError

    def transform_data(self, raw: dict) -> dict:
        return raw

    def is_charging_active(self, enabled_value) -> bool:
        raise NotImplementedError

    @property
    def min_current(self) -> int:
        raise NotImplementedError

    @property
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    def ai_modes(self) -> dict:
        raise NotImplementedError
