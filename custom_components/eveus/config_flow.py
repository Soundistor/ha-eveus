"""Config Flow – GUI-добавление новых зарядок."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .charger.v1 import ChargerV1
from .charger.v2 import ChargerV2
from .const import (
    CONF_DEVICE_PREFIX,
    CONF_IP_ADDRESS,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    MODEL_V1,
    MODEL_V2,
    SUPPORTED_MODELS,
)

_LOGGER = logging.getLogger(__name__)

_MODEL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[
            {"value": MODEL_V1, "label": SUPPORTED_MODELS[MODEL_V1]},
            {"value": MODEL_V2, "label": SUPPORTED_MODELS[MODEL_V2]},
        ],
        mode=SelectSelectorMode.DROPDOWN,
    )
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
        vol.Required(CONF_MODEL, default=MODEL_V1): _MODEL_SELECTOR,
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
            prefix = user_input.get(CONF_DEVICE_PREFIX, "")

            if prefix and any(
                entry.data.get(CONF_DEVICE_PREFIX) == prefix
                for entry in self._async_current_entries()
            ):
                errors[CONF_DEVICE_PREFIX] = "prefix_taken"
            else:
                err = await self._test_connection(ip, model, username, password)
                if err:
                    errors["base"] = err
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

    async def async_step_reconfigure(self, user_input=None):
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = user_input[CONF_IP_ADDRESS]
            model = user_input[CONF_MODEL]
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)

            if any(
                e.entry_id != entry.entry_id and e.data.get(CONF_IP_ADDRESS) == ip
                for e in self._async_current_entries()
            ):
                errors["base"] = "already_configured"
            else:
                err = await self._test_connection(ip, model, username, password)
                if err:
                    errors["base"] = err
                else:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        unique_id=ip,
                        title=f"Eveus {ip}",
                        data={
                            **entry.data,
                            CONF_IP_ADDRESS: ip,
                            CONF_MODEL: model,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                        },
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")

        # Prefix is deliberately not offered: entity unique_ids derive from it
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default=entry.data[CONF_IP_ADDRESS]): str,
                    vol.Required(CONF_MODEL, default=entry.data[CONF_MODEL]): _MODEL_SELECTOR,
                    vol.Optional(
                        CONF_USERNAME,
                        description={"suggested_value": entry.data.get(CONF_USERNAME)},
                    ): str,
                    vol.Optional(CONF_PASSWORD): str,
                }
            ),
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
            err = await self._test_connection(ip, model, username, password)
            if not err:
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
            errors["base"] = err

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
                               username: str | None, password: str | None) -> str | None:
        """Return None on success, or an error code ('invalid_auth' | 'cannot_connect')."""
        charger = (
            ChargerV1(ip, username, password, hass=self.hass)
            if model == MODEL_V1
            else ChargerV2(ip, username, password, hass=self.hass)
        )
        try:
            await charger.get_status()
            return None
        except aiohttp.ClientResponseError as exc:
            if exc.status == 401:
                return "invalid_auth"
            _LOGGER.debug("Cannot connect to %s (%s): %s", ip, model, exc)
            return "cannot_connect"
        except Exception as exc:
            _LOGGER.debug("Cannot connect to %s (%s): %s", ip, model, exc)
            return "cannot_connect"
