"""Car 2 Home integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from homeassistant.helpers import device_registry as dr

from .api import Car2HomeIngestView, Car2HomePairView, Car2HomeWsView, PairingManager
from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_SLUG,
    CONF_GARAGE_ID,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_NICKNAME,
    CONF_TARGETS,
    CONF_TOKEN,
    CONF_TOKENS,
    CONF_VIN,
    DOMAIN,
    MANUFACTURER_DEFAULT,
    PLATFORMS,
    TARGET_KIND_CAR,
    TARGET_KIND_GARAGE,
)
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
    """Migrate a config entry forward.

    v1 → v2: single ``token`` → ``tokens`` map keyed by client_id.
    v2 → v3: single-car entry → garage shape (a garage-hub target + the one car
    target), so a stale entry loads without a "migration failed" error. This is
    a MINIMAL structural wrap only — no live garage adoption, no unique_id
    re-key. The intended path for existing testers is: update the plugin + app,
    delete the old device, and re-pair to get the account-level garage.
    """
    data = dict(entry.data)

    if entry.version == 1:
        tokens: dict[str, str] = {}
        legacy = data.get(CONF_TOKEN)
        if legacy:
            tokens["default"] = legacy
        data[CONF_TOKENS] = tokens
        hass.config_entries.async_update_entry(entry, data=data, version=2)

    if entry.version == 2:
        device_id = data.get(CONF_DEVICE_ID) or entry.unique_id or "car2home"
        garage_id = f"{device_id}_garage"
        targets = {
            garage_id: {
                "kind": TARGET_KIND_GARAGE,
                "id": garage_id,
                "device_slug": "car2home",
                "model": "Garage",
                "manufacturer": MANUFACTURER_DEFAULT,
                "name": "Car 2 Home",
                "nickname": None,
                "vin": None,
            },
            device_id: {
                "kind": TARGET_KIND_CAR,
                "id": device_id,
                "device_slug": data.get(CONF_DEVICE_SLUG),
                "model": data.get(CONF_MODEL) or "Vehicle",
                "manufacturer": data.get(CONF_MANUFACTURER) or MANUFACTURER_DEFAULT,
                "nickname": data.get(CONF_NICKNAME),
                "vin": (data.get(CONF_VIN) or "").strip() or None,
                "is_primary": True,
            },
        }
        data[CONF_GARAGE_ID] = garage_id
        data[CONF_TARGETS] = targets
        hass.config_entries.async_update_entry(entry, data=data, version=3)

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow the user to delete a car device (e.g. an archived/removed car) from
    the UI. Drop it from the persisted target catalogue so a restart doesn't
    re-seed it; an active car simply reappears on the next hello."""
    target_ids = {
        ident for domain, ident in device_entry.identifiers if domain == DOMAIN
    }
    targets = dict(entry.data.get(CONF_TARGETS) or {})
    removed = [tid for tid in list(targets) if tid in target_ids]
    if removed:
        for tid in removed:
            targets.pop(tid, None)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TARGETS: targets}
        )
        # Also drop it from the live coordinator's in-memory view, otherwise the
        # next _persist_targets (which merges over entry.data) would resurrect it.
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is not None:
            for tid in removed:
                coordinator.data.get("targets", {}).pop(tid, None)
                coordinator.data.get("values", {}).pop(tid, None)
                coordinator.data.get("location", {}).pop(tid, None)
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
