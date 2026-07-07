"""Config Flow – GUI-добавление новых зарядок."""
from __future__ import annotations

import logging
from typing import Any, Mapping

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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            ip = self._reauth_entry.data[CONF_IP_ADDRESS]
            model = self._reauth_entry.data[CONF_MODEL]
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)
            if await self._test_connection(ip, model, username, password):
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Optional(CONF_USERNAME): str,
                vol.Optional(CONF_PASSWORD): str,
            }),
            description_placeholders={
                "ip_address": self._reauth_entry.data[CONF_IP_ADDRESS],
            },
            errors=errors,
        )

    async def _test_connection(self, ip: str, model: str,
                               username: str | None, password: str | None) -> bool:
        charger = ChargerV1(ip, username, password) if model == MODEL_V1 else ChargerV2(ip, username, password)
        try:
            await charger.get_status()
            return True
        except Exception as exc:
            _LOGGER.debug("Cannot connect to %s (%s): %s", ip, model, exc)
            return False
        finally:
            await charger.close()
