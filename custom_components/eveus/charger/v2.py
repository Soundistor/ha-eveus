from .base import BaseCharger
from typing import Dict

class ChargerV2(BaseCharger):
    """API v2 – у станции GBT."""

    async def get_status(self) -> Dict[str, any]:
        """Запрос `/main`, но в отличие от V1 содержит дополнительные поля."""
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
        # Для GBT: 0 – старт зарядки, 1 – остановка
        value = 0 if enabled else 1
        payload = f"evseEnabled={value}"
        await self._request("POST", "/pageEvent",
                            data=payload,
                            headers={"Content-Type": "application/x-www-form-urlencoded"})

    @property
    def capabilities(self) -> set[str]:
        """Полный набор атрибутов для GBT."""
        return {
            "state",
            "subState",
            "evseEnabled",
            "currentSet",
            "ground",
            "groundCtrl",
            "aiStatus",
            "aiVoltage",
            "temperature1",
            "temperature2",
            "powerMeas",
            "sessionEnergy",
            "sessionTime",
            "totalEnergy",
            "systemTime",
            # + любые другие поля, которые вы перечислили в yaml
        }