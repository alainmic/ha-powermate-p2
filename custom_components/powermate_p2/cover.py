"""Cover platform for PowerMate P2 Motorized Shades."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_CLOSED, STATE_OPEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import PowerMateClient, PowerMateShade
from .const import DOMAIN, RF_VALUE_CLOSE, RF_VALUE_OPEN, RF_VALUE_STOP

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PowerMate P2 cover entities from a config entry."""
    client: PowerMateClient = hass.data[DOMAIN][entry.entry_id]
    entities = [
        PowerMateShadeCover(client, shade)
        for shade in client.shades.values()
    ]
    async_add_entities(entities)


class PowerMateShadeCover(CoverEntity, RestoreEntity):
    """Representation of an RF motorized shade on a PowerMate P2 hub."""

    _attr_has_entity_name = False
    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )
    _attr_assumed_state = True

    def __init__(self, client: PowerMateClient, shade: PowerMateShade) -> None:
        """Initialize the shade cover entity."""
        self._client = client
        self._shade = shade
        self._attr_name = shade.name
        self._attr_unique_id = f"powermate_p2_{shade.device_id}"
        self._attr_is_closed: bool | None = False
        self._last_action: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry metadata for this shade."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._shade.device_id)},
            name=self._shade.name,
            manufacturer=self._shade.company or "A-OK Motor",
            model="PowerMate P2 RF Motorized Shade",
            via_device=(DOMAIN, self._shade.uid),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic state attributes."""
        return {
            "motor_company": self._shade.company,
            "device_type": self._shade.device_type,
            "last_action": self._last_action,
        }

    async def async_added_to_hass(self) -> None:
        """Restore last state and subscribe to push updates."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            if last_state.state == STATE_CLOSED:
                self._attr_is_closed = True
            elif last_state.state == STATE_OPEN:
                self._attr_is_closed = False
            self._last_action = last_state.attributes.get("last_action")

        self.async_on_remove(
            self._client.register_callback(self._handle_push_update)
        )

    @callback
    def _handle_push_update(self, device_id: str, value1: int) -> None:
        """Handle push status updates from the Orvibo server (e.g. app or timer)."""
        if device_id != self._shade.device_id:
            return
        if value1 == RF_VALUE_OPEN:
            self._attr_is_closed = False
            self._last_action = "open"
        elif value1 == RF_VALUE_CLOSE:
            self._attr_is_closed = True
            self._last_action = "close"
        elif value1 == RF_VALUE_STOP:
            self._last_action = "stop"
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the shade."""
        ok = await self._client.async_open_shade(
            self._shade.uid, self._shade.device_id
        )
        if not ok:
            raise HomeAssistantError(
                f"Failed to send Open command to {self._shade.name}"
            )
        self._attr_is_closed = False
        self._last_action = "open"
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shade."""
        ok = await self._client.async_close_shade(
            self._shade.uid, self._shade.device_id
        )
        if not ok:
            raise HomeAssistantError(
                f"Failed to send Close command to {self._shade.name}"
            )
        self._attr_is_closed = True
        self._last_action = "close"
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the shade motor."""
        ok = await self._client.async_stop_shade(
            self._shade.uid, self._shade.device_id
        )
        if not ok:
            raise HomeAssistantError(
                f"Failed to send Stop command to {self._shade.name}"
            )
        self._last_action = "stop"
        self.async_write_ha_state()
