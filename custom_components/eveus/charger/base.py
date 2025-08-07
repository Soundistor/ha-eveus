"""Базовый класс для всех зарядок."""
from __future__ import annotations

import aiohttp
import async_timeout
from typing import Any, Dict

class BaseCharger:
    """Общая часть: открытие сессии, запросы, базовый интерфейс."""

    def __init__(self, ip: str, username: str | None = None,
                 password: str | None = None) -> None:
        self.ip = ip
        self.auth = aiohttp.BasicAuth(username, password) if username else None
        self.session: aiohttp.ClientSession | None = None

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Выполнить запрос к станции и вернуть JSON."""
        url = f"http://{self.ip}{path}"
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(auth=self.auth, timeout=timeout)

        async with async_timeout.timeout(10):
            async with self.session.request(method, url, **kwargs) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_status(self) -> Dict[str, Any]:
        """Вернуть текущий статус – переопределяется в дочерних классах."""
        raise NotImplementedError

    async def set_current(self, value: int) -> None:
        """Установить ток (A)."""
        raise NotImplementedError

    async def set_ai_mode(self, mode: int) -> None:
        """Установить режим AI (0‑off, 1‑voltage, 2‑auto, 3‑power)."""
        raise NotImplementedError

    async def set_enabled(self, enabled: bool) -> None:
        """Включить/выключить зарядку."""
        raise NotImplementedError

    async def close(self) -> None:
        """Корректно закрыть HTTP‑сессию."""
        if self.session:
            await self.session.close()