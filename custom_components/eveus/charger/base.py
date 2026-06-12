"""Базовый класс для всех зарядок."""
from __future__ import annotations

import aiohttp


class BaseCharger:
    """Общая часть: открытие сессии, запросы, базовый интерфейс."""

    def __init__(self, ip: str, username: str | None = None,
                 password: str | None = None) -> None:
        self.ip = ip
        self.auth = aiohttp.BasicAuth(username, password or "") if username else None
        self.session: aiohttp.ClientSession | None = None

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"http://{self.ip}{path}"
        if not self.session:
            self.session = aiohttp.ClientSession(
                auth=self.auth,
                timeout=aiohttp.ClientTimeout(total=10),
            )
        async with self.session.request(method, url, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_status(self) -> Dict[str, Any]:
        raise NotImplementedError

    async def set_current(self, value: int) -> None:
        raise NotImplementedError

    async def set_ai_mode(self, mode: int) -> None:
        raise NotImplementedError

    async def set_enabled(self, enabled: bool) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        if self.session:
            await self.session.close()

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
