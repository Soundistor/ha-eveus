"""Config Flow – GUI‑добавление новых зарядок."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_IP_ADDRESS,
    CONF_MODEL,
    CONF_USERNAME,
    CONF_PASSWORD,
    SUPPORTED_MODELS,
    MODEL_V1,
    MODEL_V2,
)
from .charger.v1 import ChargerV1
from .charger.v2 import ChargerV2

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
        vol.Required(CONF_MODEL, default=MODEL_V1): vol.In(SUPPORTED_MODELS),
        vol.Optional(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
    }
)


class MyEVChargerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Хэндлер пользовательского потока конфигурации."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Первый шаг – ввод IP, модели и авторизации."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = user_input[CONF_IP_ADDRESS]
            model = user_input[CONF_MODEL]
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)

            # Пробуем подключиться к станции, чтобы убедиться, что всё ок.
            if not await self._test_connection(ip, model, username, password):
                errors["base"] = "cannot_connect"
            else:
                # Делаем IP уникальным ID (можно дополнить MAC, если он есть)
                await self.async_set_unique_id(ip)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"EV charger {ip}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _test_connection(self, ip: str, model: str,
                               username: str | None,
                               password: str | None) -> bool:
        """Краткая проверка – запрос `/main`."""
        try:
            charger = ChargerV1(ip, username, password) if model == MODEL_V1 else ChargerV2(ip, username, password)
            async with self.hass.timeout(5):
                await charger.get_status()
            await charger.close()
            return True
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.debug("Cannot connect to %s (%s): %s", ip, model, exc)
            return False

class MyEVChargerOptionsFlowHandler(config_entries.OptionsFlow):
    """Обработчик опций – интервал обновления."""

    def __init__(self, entry: config_entries.ConfigEntry):
        self.entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required("update_interval", default=self.entry.options.get("update_interval", 30)): vol.All(
                    int, vol.Range(min=5, max=300)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)