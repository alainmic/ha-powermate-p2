"""Test configuration and lightweight Home Assistant stubs if running outside HA core."""

from __future__ import annotations

from enum import IntFlag, StrEnum
import sys
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock


def _install_ha_stubs_if_missing() -> None:
    """Install minimal Home Assistant module stubs when running in a bare Python venv."""
    try:
        import voluptuous  # noqa: F401
    except ImportError:
        vol_mod = ModuleType("voluptuous")
        vol_mod.Schema = lambda schema, **kwargs: schema
        vol_mod.Required = lambda key, **kwargs: key
        vol_mod.Optional = lambda key, **kwargs: key
        sys.modules["voluptuous"] = vol_mod

    try:
        import homeassistant  # noqa: F401
        return
    except ImportError:
        pass

    ha = ModuleType("homeassistant")
    ha_const = ModuleType("homeassistant.const")
    ha_const.CONF_USERNAME = "username"
    ha_const.CONF_PASSWORD = "password"
    ha_const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
    ha_const.STATE_OPEN = "open"
    ha_const.STATE_CLOSED = "closed"

    class Platform(StrEnum):
        COVER = "cover"

    ha_const.Platform = Platform

    ha_core = ModuleType("homeassistant.core")

    class HomeAssistant:
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}
            self.bus = MagicMock()
            self.config_entries = MagicMock()

    class Event:
        pass

    def callback(func: Any) -> Any:
        return func

    ha_core.HomeAssistant = HomeAssistant
    ha_core.Event = Event
    ha_core.callback = callback

    ha_exceptions = ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    class ConfigEntryNotReady(HomeAssistantError):
        pass

    class AbortFlow(Exception):
        def __init__(self, reason: str) -> None:
            super().__init__(reason)
            self.reason = reason

    ha_exceptions.HomeAssistantError = HomeAssistantError
    ha_exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    ha_exceptions.ConfigEntryNotReady = ConfigEntryNotReady

    ha_config_entries = ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        def __init__(
            self,
            entry_id: str = "entry_123",
            data: dict[str, Any] | None = None,
            title: str = "PowerMate P2",
        ) -> None:
            self.entry_id = entry_id
            self.data = data or {}
            self.title = title
            self._unload_callbacks: list[Any] = []

        def async_on_unload(self, func: Any) -> None:
            self._unload_callbacks.append(func)

    class ConfigFlow:
        def __init_subclass__(
            cls, domain: str | None = None, **kwargs: Any
        ) -> None:
            super().__init_subclass__(**kwargs)
            cls.domain = domain

        def __init__(self) -> None:
            self.hass: Any = None
            self.context: dict[str, Any] = {}
            self._unique_id: str | None = None
            self._existing_unique_ids: set[str] = set()

        async def async_set_unique_id(self, unique_id: str) -> None:
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            if self._unique_id in self._existing_unique_ids:
                raise AbortFlow("already_configured")

        def async_create_entry(
            self, *, title: str, data: dict[str, Any]
        ) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any = None,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "errors": errors or {},
                "description_placeholders": description_placeholders,
            }

        def async_update_reload_and_abort(
            self, entry: ConfigEntry, *, data: dict[str, Any]
        ) -> dict[str, Any]:
            entry.data = data
            return {"type": "abort", "reason": "reauth_successful"}

    ha_config_entries.ConfigEntry = ConfigEntry
    ha_config_entries.ConfigFlow = ConfigFlow
    ha_config_entries.AbortFlow = AbortFlow

    ha_def = ModuleType("homeassistant.data_entry_flow")
    ha_def.FlowResult = dict[str, Any]

    ha_helpers = ModuleType("homeassistant.helpers")
    ha_dr = ModuleType("homeassistant.helpers.device_registry")
    ha_dr.DeviceInfo = dict
    ha_dr.async_get = MagicMock()
    ha_helpers.device_registry = ha_dr

    ha_ep = ModuleType("homeassistant.helpers.entity_platform")
    ha_ep.AddEntitiesCallback = Any

    ha_rs = ModuleType("homeassistant.helpers.restore_state")

    class RestoreEntity:
        async def async_added_to_hass(self) -> None:
            pass

        async def async_get_last_state(self) -> Any:
            return None

        def async_on_remove(self, func: Any) -> None:
            pass

        def async_write_ha_state(self) -> None:
            pass

    ha_rs.RestoreEntity = RestoreEntity

    ha_comp = ModuleType("homeassistant.components")
    ha_cover = ModuleType("homeassistant.components.cover")

    class CoverDeviceClass(StrEnum):
        SHADE = "shade"

    class CoverEntityFeature(IntFlag):
        OPEN = 1
        CLOSE = 2
        SET_POSITION = 4
        STOP = 8

    class CoverEntity:
        @property
        def name(self) -> str | None:
            return getattr(self, "_attr_name", None)

        @property
        def unique_id(self) -> str | None:
            return getattr(self, "_attr_unique_id", None)

        @property
        def assumed_state(self) -> bool:
            return getattr(self, "_attr_assumed_state", False)

        @property
        def is_closed(self) -> bool | None:
            return getattr(self, "_attr_is_closed", None)

    ha_cover.CoverDeviceClass = CoverDeviceClass
    ha_cover.CoverEntityFeature = CoverEntityFeature
    ha_cover.CoverEntity = CoverEntity

    ha_diag = ModuleType("homeassistant.components.diagnostics")
    REDACTED = "**REDACTED**"

    def async_redact_data(data: Any, to_redact: set[str]) -> Any:
        if isinstance(data, dict):
            return {
                k: (
                    REDACTED
                    if k in to_redact
                    else async_redact_data(v, to_redact)
                )
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [async_redact_data(item, to_redact) for item in data]
        return data

    ha_diag.async_redact_data = async_redact_data

    for name, mod in {
        "homeassistant": ha,
        "homeassistant.const": ha_const,
        "homeassistant.core": ha_core,
        "homeassistant.exceptions": ha_exceptions,
        "homeassistant.config_entries": ha_config_entries,
        "homeassistant.data_entry_flow": ha_def,
        "homeassistant.helpers": ha_helpers,
        "homeassistant.helpers.device_registry": ha_dr,
        "homeassistant.helpers.entity_platform": ha_ep,
        "homeassistant.helpers.restore_state": ha_rs,
        "homeassistant.components": ha_comp,
        "homeassistant.components.cover": ha_cover,
        "homeassistant.components.diagnostics": ha_diag,
    }.items():
        sys.modules[name] = mod


_install_ha_stubs_if_missing()
