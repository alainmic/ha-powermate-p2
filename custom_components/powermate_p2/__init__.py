"""The PowerMate P2 Motorized Shades integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .client import (
    PowerMateAuthError,
    PowerMateClient,
    PowerMateConnectionError,
)
from .const import CONF_FAMILY_ID, CONF_PASSWORD_HASH, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PowerMate P2 from a config entry."""
    username: str = entry.data[CONF_USERNAME]
    password_hash: str = entry.data[CONF_PASSWORD_HASH]
    family_id: str | None = entry.data.get(CONF_FAMILY_ID)

    client = PowerMateClient(
        username=username,
        password_hash=password_hash,
        family_id=family_id,
    )

    try:
        await client.async_discover_devices()
    except PowerMateAuthError as err:
        await client.async_close()
        raise ConfigEntryAuthFailed(
            f"Authentication failed for {username}: {err}"
        ) from err
    except (PowerMateConnectionError, Exception) as err:
        await client.async_close()
        raise ConfigEntryNotReady(
            f"Unable to connect to PowerMate P2 cloud: {err}"
        ) from err

    dev_reg = dr.async_get(hass)
    for gw in client.gateways.values():
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, gw.uid)},
            manufacturer="Orvibo / PowerMate",
            name=f"PowerMate P2 Hub ({gw.name})",
            model="Allone Pro (RF/IR Bridge)",
            serial_number=gw.uid,
        )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client

    async def _async_close_on_stop(_event: Event) -> None:
        await client.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, _async_close_on_stop
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unload_ok:
        client: PowerMateClient | None = hass.data[DOMAIN].pop(
            entry.entry_id, None
        )
        if client is not None:
            await client.async_close()
    return unload_ok
