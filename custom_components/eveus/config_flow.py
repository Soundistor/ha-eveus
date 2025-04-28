from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol

from .const import DOMAIN, DEFAULT_NAME, DEFAULT_HOST, DEFAULT_USERNAME, DEFAULT_PASSWORD

class EveusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Eveus."""

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Проверка подключения (можно добавить try/except)
            return self.async_create_entry(title=user_input["name"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("name", default=DEFAULT_NAME): str,
                vol.Required("host", default=DEFAULT_HOST): str,
                vol.Required("username", default=DEFAULT_USERNAME): str,
                vol.Required("password", default=DEFAULT_PASSWORD): str,
            }),
            errors=errors,
        )