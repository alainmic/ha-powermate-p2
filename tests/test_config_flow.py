"""Unit tests for the PowerMate P2 config flow and reauth flow."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import tests.conftest  # noqa: F401
from homeassistant.config_entries import AbortFlow, ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.powermate_p2.client import (
    PowerMateAuthError,
    PowerMateConnectionError,
    md5_upper,
)
from custom_components.powermate_p2.config_flow import PowerMateConfigFlow
from custom_components.powermate_p2.const import CONF_FAMILY_ID, CONF_PASSWORD_HASH


class TestPowerMateConfigFlow(unittest.IsolatedAsyncioTestCase):
    """Test cases for PowerMateConfigFlow."""

    async def test_user_flow_success(self) -> None:
        """Test successful user configuration step."""
        flow = PowerMateConfigFlow()

        form = await flow.async_step_user()
        self.assertEqual(form["type"], "form")
        self.assertEqual(form["step_id"], "user")

        with patch(
            "custom_components.powermate_p2.config_flow.PowerMateClient"
        ) as mock_cls:
            instance = mock_cls.return_value
            instance.family_id = "family_test_001"
            instance.async_discover_devices = AsyncMock(return_value={})
            instance.async_close = AsyncMock()

            result = await flow.async_step_user(
                {
                    CONF_USERNAME: "user@example.com",
                    CONF_PASSWORD: "my_secret_password",
                }
            )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "PowerMate P2 (user@example.com)")
        self.assertEqual(
            result["data"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD_HASH: md5_upper("my_secret_password"),
                CONF_FAMILY_ID: "family_test_001",
            },
        )
        instance.async_close.assert_awaited()

    async def test_user_flow_errors(self) -> None:
        """Test error handling in user config flow."""
        cases = [
            (PowerMateAuthError("bad login"), "invalid_auth"),
            (PowerMateConnectionError("timeout"), "cannot_connect"),
            (RuntimeError("boom"), "unknown"),
        ]
        for exc, expected_error in cases:
            with self.subTest(error=expected_error):
                flow = PowerMateConfigFlow()
                with patch(
                    "custom_components.powermate_p2.config_flow.PowerMateClient"
                ) as mock_cls:
                    instance = mock_cls.return_value
                    instance.async_discover_devices = AsyncMock(side_effect=exc)
                    instance.async_close = AsyncMock()

                    result = await flow.async_step_user(
                        {
                            CONF_USERNAME: "user@example.com",
                            CONF_PASSWORD: "my_secret_password",
                        }
                    )

                self.assertEqual(result["type"], "form")
                self.assertEqual(result["errors"], {"base": expected_error})
                instance.async_close.assert_awaited()

    async def test_user_flow_already_configured(self) -> None:
        """Test abort when account is already configured."""
        flow = PowerMateConfigFlow()
        flow._existing_unique_ids = {"user@example.com"}

        with self.assertRaises(AbortFlow) as ctx:
            await flow.async_step_user(
                {
                    CONF_USERNAME: "User@Example.com",
                    CONF_PASSWORD: "my_secret_password",
                }
            )
        self.assertEqual(str(ctx.exception), "already_configured")

    async def test_reauth_flow_success_and_error(self) -> None:
        """Test reauthentication flow."""
        entry = ConfigEntry(
            entry_id="entry_001",
            data={
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD_HASH: md5_upper("old_password"),
                CONF_FAMILY_ID: "family_test_001",
            },
        )
        flow = PowerMateConfigFlow()
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = entry
        flow.context = {"entry_id": "entry_001"}

        form = await flow.async_step_reauth(entry.data)
        self.assertEqual(form["type"], "form")
        self.assertEqual(form["step_id"], "reauth_confirm")

        with patch(
            "custom_components.powermate_p2.config_flow.PowerMateClient"
        ) as mock_cls:
            instance = mock_cls.return_value
            instance.async_discover_devices = AsyncMock(
                side_effect=PowerMateAuthError("bad")
            )
            instance.async_close = AsyncMock()

            err_res = await flow.async_step_reauth_confirm(
                {CONF_PASSWORD: "wrong_new_password"}
            )
            self.assertEqual(err_res["errors"], {"base": "invalid_auth"})

        with patch(
            "custom_components.powermate_p2.config_flow.PowerMateClient"
        ) as mock_cls:
            instance = mock_cls.return_value
            instance.family_id = "family_test_001"
            instance.async_discover_devices = AsyncMock(return_value={})
            instance.async_close = AsyncMock()

            ok_res = await flow.async_step_reauth_confirm(
                {CONF_PASSWORD: "new_valid_password"}
            )

        self.assertEqual(ok_res["type"], "abort")
        self.assertEqual(ok_res["reason"], "reauth_successful")
        self.assertEqual(
            entry.data[CONF_PASSWORD_HASH], md5_upper("new_valid_password")
        )


if __name__ == "__main__":
    unittest.main()
