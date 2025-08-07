from .base import BaseCharger
from typing import Dict

class ChargerV1(BaseCharger):
    """API v1 – у станции Bolt/Eveus."""

    async def get_status(self) -> Dict[str, any]:
        """
        Точка `/main` возвращает JSON вида:
        {"evseEnabled":0,"state":3,"currentSet":16,...}
        """
        return await self._request("GET", "/main")

    async def set_current(self, value: int) -> None:
        payload = f"currentSet={value:02d}"
        await self._request("POST", "/pageEvent",
                            data=payload,
                            headers={"Content-Type": "application/x-www-form-urlencoded"})

    async def set_ai_mode(self, mode: int) -> None:
        payload = f"pageevent=evseEnabled&aiMode={mode}"
        await self._request("POST", "/pageEvent",
                            data=payload,
                            headers={"Content-Type": "application/x-www-form-urlencoded"})

    async def set_enabled(self, enabled: bool) -> None:
        # у v1 выключение = 0, включение = 1 (соответственно evseEnabled)
        value = 1 if enabled else 0
        payload = f"evseEnabled={value}"
        await self._request("POST", "/pageEvent",
                            data=payload,
                            headers={"Content-Type": "application/x-www-form-urlencoded"})

    @property
    def capabilities(self) -> set[str]:
        """Что поддерживает эта модель."""
        return {
            "state",
            "evseEnabled",
            "currentSet",
            "ground",
            "groundCtrl",
            "aiStatus",
            "aiVoltage",
            "temperature1",
            # …полный набор атрибутов, которые вы запрашивали в yaml‑sensor
        }