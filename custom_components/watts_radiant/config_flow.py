"""Config flow for Watts Radiant — login first, devices later."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WattsAuthClient, WattsAuthError, WattsInvalidAuth
from .const import DOMAIN


class WattsRadiantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Watts Radiant."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step: Watts account email + password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = WattsAuthClient(session)
            try:
                tokens = await client.authenticate(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except WattsInvalidAuth:
                errors["base"] = "invalid_auth"
            except WattsAuthError:
                errors["base"] = "cannot_connect"
            else:
                # Password is deliberately NOT stored: only the
                # tokens, which the coordinator refreshes.
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        "tokens": tokens.to_dict(),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
