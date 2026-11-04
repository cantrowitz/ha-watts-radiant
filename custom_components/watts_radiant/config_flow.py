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

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth: HA starts this when the stored refresh token is rejected.

        The entry being reauthed is identified by the reauth context
        (falling back to the flow handler, which HA sets to the entry
        id for reauth flows).
        """
        entry_id = (self.context or {}).get("entry_id") or self.handler
        self._reauth_entry = self.hass.config_entries.async_get_entry(entry_id)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Re-authenticate with email + password and update the entry's tokens."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_USERNAME].lower()
            # The reauth must be for the SAME account: abort when the
            # email does not match the entry being re-authenticated,
            # so a different account's tokens never land on this entry
            # (which would keep the old unique id and devices).
            await self.async_set_unique_id(email)
            self._abort_if_unique_id_mismatch(reason="wrong_account")

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
                # Password is deliberately NOT stored: only the new
                # tokens, which the coordinator refreshes from here on.
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        "tokens": tokens.to_dict(),
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
