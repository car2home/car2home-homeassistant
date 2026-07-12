"""Diagnostics support for Car 2 Home."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, CONF_TOKENS, CONF_VIN, DOMAIN
from .coordinator import Car2HomeCoordinator

TO_REDACT = {CONF_TOKEN, CONF_TOKENS, CONF_VIN, "token", "tokens", "vin", "latitude", "longitude"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: Car2HomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        # Per-target catalogue (garage hub + cars), values and location namespaces.
        "targets": async_redact_data(coordinator.data.get("targets", {}), TO_REDACT),
        "values": coordinator.data.get("values", {}),
        "location": async_redact_data(coordinator.data.get("location", {}), TO_REDACT),
        "ws_connected": coordinator.data.get("ws_connected", False),
    }
