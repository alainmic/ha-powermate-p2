"""Config flow for PowerMate P2 Motorized Shades."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .client import (
    PowerMateAuthError,
    PowerMateClient,
    PowerMateConnectionError,
    md5_upper,
)
from .const import CONF_FAMILY_ID, CONF_PASSWORD_HASH, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class PowerMateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PowerMate P2."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            password_hash = md5_upper(password)

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            client = PowerMateClient(
                username=username, password_hash=password_hash
            )
            try:
                await client.async_discover_devices()
            except PowerMateAuthError:
                errors["base"] = "invalid_auth"
            except PowerMateConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error setting up PowerMate P2")
                errors["base"] = "unknown"
            else:
                family_id = client.family_id
                return self.async_create_entry(
                    title=f"PowerMate P2 ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD_HASH: password_hash,
                        CONF_FAMILY_ID: family_id,
                    },
                )
            finally:
                await client.async_close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Handle reauthentication when credentials become invalid."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm reauthentication credentials."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        username = self._reauth_entry.data[CONF_USERNAME]

        if user_input is not None:
            password_hash = md5_upper(user_input[CONF_PASSWORD])
            client = PowerMateClient(
                username=username, password_hash=password_hash
            )
            try:
                await client.async_discover_devices()
            except PowerMateAuthError:
                errors["base"] = "invalid_auth"
            except PowerMateConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error reauthenticating PowerMate P2")
                errors["base"] = "unknown"
            else:
                family_id = client.family_id or self._reauth_entry.data.get(
                    CONF_FAMILY_ID
                )
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD_HASH: password_hash,
                        CONF_FAMILY_ID: family_id,
                    },
                )
            finally:
                await client.async_close()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: username},
            errors=errors,
        )
