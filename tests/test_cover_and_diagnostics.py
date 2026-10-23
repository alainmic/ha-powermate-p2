"""Unit tests for PowerMate P2 setup, cover entities, and diagnostics redaction."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import tests.conftest  # noqa: F401
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, STATE_CLOSED
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)

from custom_components.powermate_p2 import async_setup_entry, async_unload_entry
from custom_components.powermate_p2.client import (
    PowerMateAuthError,
    PowerMateConnectionError,
    PowerMateGateway,
    PowerMateShade,
)
from custom_components.powermate_p2.const import (
    CONF_FAMILY_ID,
    CONF_PASSWORD_HASH,
    DOMAIN,
    RF_VALUE_CLOSE,
    RF_VALUE_OPEN,
    RF_VALUE_STOP,
)
from custom_components.powermate_p2.cover import (
    PowerMateShadeCover,
    async_setup_entry as async_setup_cover_entry,
)
from custom_components.powermate_p2.diagnostics import (
    async_get_config_entry_diagnostics,
)


def _make_fake_client() -> MagicMock:
    client = MagicMock()
    client.connected = True
    client.gateways = {
        "aabbccddeeff": PowerMateGateway(
            uid="aabbccddeeff",
            device_id="gw_001",
            name="Allone Pro",
            model="model_001",
            online=True,
        )
    }
    client.shades = {
        "shade_001": PowerMateShade(
            device_id="shade_001",
            uid="aabbccddeeff",
            name="Living Room Shade",
            raw_name="Living Room Shade",
            company="A-OK Motor",
            model="model_001",
            device_type=42,
        )
    }
    client.async_discover_devices = AsyncMock(return_value=client.shades)
    client.async_close = AsyncMock()
    client.async_open_shade = AsyncMock(return_value=True)
    client.async_close_shade = AsyncMock(return_value=True)
    client.async_stop_shade = AsyncMock(return_value=True)
    client.register_callback = MagicMock(return_value=lambda: None)
    return client


class TestPowerMateCoverAndDiagnostics(unittest.IsolatedAsyncioTestCase):
    """Test cases for integration setup, cover entities, and diagnostics."""

    async def test_setup_and_unload_entry(self) -> None:
        """Test setting up and unloading a config entry."""
        hass = HomeAssistant()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        hass.config_entries.async_unload_platforms = AsyncMock(
            return_value=True
        )

        entry = ConfigEntry(
            entry_id="entry_001",
            data={
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD_HASH: "0123456789ABCDEF0123456789ABCDEF",
                CONF_FAMILY_ID: "family_001",
            },
        )

        fake_client = _make_fake_client()
        with patch(
            "custom_components.powermate_p2.PowerMateClient",
            return_value=fake_client,
        ):
            self.assertTrue(await async_setup_entry(hass, entry))
            self.assertIs(hass.data[DOMAIN]["entry_001"], fake_client)

            self.assertTrue(await async_unload_entry(hass, entry))
            self.assertNotIn("entry_001", hass.data[DOMAIN])
            fake_client.async_close.assert_awaited()

    async def test_setup_entry_auth_and_connection_failures(self) -> None:
        """Test ConfigEntryAuthFailed and ConfigEntryNotReady during setup."""
        hass = HomeAssistant()
        entry = ConfigEntry(
            entry_id="entry_001",
            data={
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD_HASH: "0123456789ABCDEF0123456789ABCDEF",
            },
        )

        client_auth = _make_fake_client()
        client_auth.async_discover_devices = AsyncMock(
            side_effect=PowerMateAuthError("expired")
        )
        with (
            patch(
                "custom_components.powermate_p2.PowerMateClient",
                return_value=client_auth,
            ),
            self.assertRaises(ConfigEntryAuthFailed),
        ):
            await async_setup_entry(hass, entry)

        client_conn = _make_fake_client()
        client_conn.async_discover_devices = AsyncMock(
            side_effect=PowerMateConnectionError("offline")
        )
        with (
            patch(
                "custom_components.powermate_p2.PowerMateClient",
                return_value=client_conn,
            ),
            self.assertRaises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

    async def test_cover_entity_lifecycle_and_actions(self) -> None:
        """Test cover entity creation, state restoration, Open/Close/Stop, and push callbacks."""
        hass = HomeAssistant()
        entry = ConfigEntry(entry_id="entry_001", data={})
        fake_client = _make_fake_client()
        hass.data[DOMAIN] = {"entry_001": fake_client}

        added: list[PowerMateShadeCover] = []
        await async_setup_cover_entry(hass, entry, added.extend)
        self.assertEqual(len(added), 1)

        cover = added[0]
        self.assertEqual(cover.name, "Living Room Shade")
        self.assertEqual(cover.unique_id, "powermate_p2_shade_001")
        self.assertTrue(cover.assumed_state)
        self.assertEqual(cover.device_info["manufacturer"], "A-OK Motor")

        cover.async_get_last_state = AsyncMock(
            return_value=SimpleNamespace(
                state=STATE_CLOSED, attributes={"last_action": "close"}
            )
        )
        await cover.async_added_to_hass()
        self.assertTrue(cover._attr_is_closed)
        self.assertEqual(cover.extra_state_attributes["last_action"], "close")

        await cover.async_open_cover()
        self.assertFalse(cover._attr_is_closed)
        self.assertEqual(cover.extra_state_attributes["last_action"], "open")

        await cover.async_stop_cover()
        self.assertEqual(cover.extra_state_attributes["last_action"], "stop")

        await cover.async_close_cover()
        self.assertTrue(cover._attr_is_closed)
        self.assertEqual(cover.extra_state_attributes["last_action"], "close")

        cover._handle_push_update("other_shade", RF_VALUE_OPEN)
        self.assertTrue(cover._attr_is_closed)

        cover._handle_push_update("shade_001", RF_VALUE_OPEN)
        self.assertFalse(cover._attr_is_closed)
        self.assertEqual(cover.extra_state_attributes["last_action"], "open")

        cover._handle_push_update("shade_001", RF_VALUE_STOP)
        self.assertEqual(cover.extra_state_attributes["last_action"], "stop")

        cover._handle_push_update("shade_001", RF_VALUE_CLOSE)
        self.assertTrue(cover._attr_is_closed)
        self.assertEqual(cover.extra_state_attributes["last_action"], "close")

        fake_client.async_open_shade = AsyncMock(return_value=False)
        with self.assertRaises(HomeAssistantError):
            await cover.async_open_cover()

        fake_client.async_close_shade = AsyncMock(return_value=False)
        with self.assertRaises(HomeAssistantError):
            await cover.async_close_cover()

        fake_client.async_stop_shade = AsyncMock(return_value=False)
        with self.assertRaises(HomeAssistantError):
            await cover.async_stop_cover()

    async def test_diagnostics_redaction(self) -> None:
        """Ensure all credentials, family_id, uids, and device_ids are redacted in diagnostics."""
        hass = HomeAssistant()
        entry = ConfigEntry(
            entry_id="entry_001",
            data={
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD_HASH: "0123456789ABCDEF0123456789ABCDEF",
                CONF_FAMILY_ID: "secret_family_id",
            },
        )
        fake_client = _make_fake_client()
        hass.data[DOMAIN] = {"entry_001": fake_client}

        diag = await async_get_config_entry_diagnostics(hass, entry)
        self.assertEqual(diag["entry"][CONF_USERNAME], "**REDACTED**")
        self.assertEqual(diag["entry"][CONF_PASSWORD_HASH], "**REDACTED**")
        self.assertEqual(diag["entry"][CONF_FAMILY_ID], "**REDACTED**")
        self.assertEqual(diag["gateways"][0]["uid"], "**REDACTED**")
        self.assertEqual(diag["gateways"][0]["device_id"], "**REDACTED**")
        self.assertEqual(diag["shades"][0]["uid"], "**REDACTED**")
        self.assertEqual(diag["shades"][0]["device_id"], "**REDACTED**")
        self.assertEqual(diag["shades"][0]["name"], "Living Room Shade")


if __name__ == "__main__":
    unittest.main()
