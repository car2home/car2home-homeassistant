"""Diagnostics support for Car 2 Home."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, DOMAIN
from .coordinator import Car2HomeCoordinator

TO_REDACT = {CONF_TOKEN, "token", "latitude", "longitude"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: Car2HomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "descriptor": async_redact_data(coordinator.data.get("descriptor") or {}, TO_REDACT),
        "values": coordinator.data.get("values", {}),
        "ws_connected": coordinator.data.get("ws_connected", False),
    }
