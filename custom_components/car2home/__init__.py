"""Car 2 Home integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .api import Car2HomeIngestView, Car2HomePairView, Car2HomeWsView, PairingManager
from .const import CONF_TOKEN, CONF_TOKENS, DOMAIN, PLATFORMS
from .coordinator import Car2HomeCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@callback
def _ensure_global_setup(hass: HomeAssistant) -> None:
    """Register the pairing manager and HTTP/WS views exactly once.

    Config-flow-only integrations do NOT trigger ``async_setup`` on HA startup
    when there's no config entry yet, so the flow itself has to guarantee the
    global state is initialized before the first pairing attempt. This helper
    is idempotent and safe to call from both ``async_setup`` and
    ``async_step_user`` / ``async_step_zeroconf``.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "_pairing" not in domain_data:
        pairing = PairingManager(hass)
        domain_data["_pairing"] = pairing
        hass.http.register_view(Car2HomePairView(pairing))
    if "_ws_view_registered" not in domain_data:
        hass.http.register_view(Car2HomeWsView(hass))
        hass.http.register_view(Car2HomeIngestView(hass))
        domain_data["_ws_view_registered"] = True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Car 2 Home integration (global)."""
    _ensure_global_setup(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to the multi-token shape (v1 → v2).

    v1 stored a single ``token``; v2 stores a ``tokens`` map keyed by the paired
    phone's client_id. We seed the map from the legacy token and KEEP the legacy
    ``token`` key so an existing paired phone keeps authenticating with no
    re-pair (``_find_coordinator_by_token`` still matches it).
    """
    if entry.version == 1:
        tokens: dict[str, str] = {}
        legacy = entry.data.get(CONF_TOKEN)
        if legacy:
            tokens["default"] = legacy
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKENS: tokens}, version=2
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Car 2 Home from a config entry."""
    _ensure_global_setup(hass)

    coordinator = Car2HomeCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: Car2HomeCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
