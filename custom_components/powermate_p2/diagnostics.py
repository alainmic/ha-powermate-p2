"""Diagnostics support for PowerMate P2 Motorized Shades."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .client import PowerMateClient
from .const import CONF_FAMILY_ID, CONF_PASSWORD_HASH, DOMAIN

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PASSWORD_HASH,
    CONF_FAMILY_ID,
    "user_id",
    "uid",
    "device_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry with sensitive fields redacted."""
    client: PowerMateClient = hass.data[DOMAIN][entry.entry_id]

    data = {
        "entry": dict(entry.data),
        "connected": client.connected,
        "gateways": [asdict(gw) for gw in client.gateways.values()],
        "shades": [asdict(sh) for sh in client.shades.values()],
    }
    return async_redact_data(data, TO_REDACT)
