"""Базовый класс для всех зарядок."""
from __future__ import annotations

import aiohttp

_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_TIMEOUT = aiohttp.ClientTimeout(total=10)

AI_MODE_MAP = {0: "off", 1: "voltage", 2: "tesla_auto", 3: "power"}


class BaseCharger:
    """Общая часть: запросы через общую сессию HA, базовый интерфейс.

    Сессию отдаёт Home Assistant (`async_get_clientsession`) — интеграция её не
    создаёт и не закрывает. `hass` необязателен: юнит-тесты `transform_data`
    инстанцируют зарядку без него и не делают сетевых запросов.
    """

    def __init__(self, ip: str, username: str | None = None,
                 password: str | None = None, hass=None) -> None:
        self.ip = ip
        self.auth = aiohttp.BasicAuth(username, password or "") if username else None
        self._hass = hass
        self._session: aiohttp.ClientSession | None = None

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        if self._session is None:
            # Lazy import: keeps the module importable without homeassistant
            # (the charger package is loaded standalone in unit tests).
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            self._session = async_get_clientsession(self._hass)
        url = f"http://{self.ip}{path}"
        async with self._session.request(
            method, url, auth=self.auth, timeout=_TIMEOUT, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post_page_event(self, data: str) -> None:
        await self._request("POST", "/pageEvent", data=data, headers=_FORM_HEADERS)

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
