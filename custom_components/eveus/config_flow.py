"""Config Flow – GUI-добавление новых зарядок."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    CONF_IP_ADDRESS,
    CONF_MODEL,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_PREFIX,
    SUPPORTED_MODELS,
    MODEL_V1,
    MODEL_V2,
)
from .charger.v1 import ChargerV1
from .charger.v2 import ChargerV2

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
        vol.Required(CONF_MODEL, default=MODEL_V1): SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": MODEL_V1, "label": SUPPORTED_MODELS[MODEL_V1]},
                    {"value": MODEL_V2, "label": SUPPORTED_MODELS[MODEL_V2]},
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_DEVICE_PREFIX, default=""): str,
    }
)


class MyEVChargerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = user_input[CONF_IP_ADDRESS]
            model = user_input[CONF_MODEL]
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)

            if not await self._test_connection(ip, model, username, password):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(ip)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Eveus {ip}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _test_connection(self, ip: str, model: str,
                               username: str | None, password: str | None) -> bool:
        try:
            charger = ChargerV1(ip, username, password) if model == MODEL_V1 else ChargerV2(ip, username, password)
            await charger.get_status()
            await charger.close()
            return True
        except Exception as exc:
            _LOGGER.debug("Cannot connect to %s (%s): %s", ip, model, exc)
            return False

    @staticmethod
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return MyEVChargerOptionsFlowHandler(entry)


class MyEVChargerOptionsFlowHandler(config_entries.OptionsFlow):

    def __init__(self, entry: config_entries.ConfigEntry):
        self.entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    "update_interval",
                    default=self.entry.options.get("update_interval", 30),
                ): vol.All(int, vol.Range(min=5, max=300))
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
