"""Base entity for Car 2 Home.

Key design choice (user requirement): data entities NEVER report unavailable.
Transport state is surfaced via a separate diagnostic binary_sensor
(`binary_sensor.*_ws_connected`), so lovelace cards that rely on historical
state keep rendering even after app/network outages.
"""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_SLUG,
    CONF_HW_VERSION,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_SW_VERSION,
    CONF_VIN,
    DOMAIN,
    MANUFACTURER_DEFAULT,
)
from .coordinator import Car2HomeCoordinator
from .slug import build_base_slug


class Car2HomeEntity(CoordinatorEntity[Car2HomeCoordinator]):
    """Shared entity base with DeviceInfo derived from the config entry.

    unique_id convention (mirrors the app's MQTT naming):
        {device_slug}_{sensor_id}
    where device_slug = car2home_{manufacturer}_{model}[_{N}], producing
    Entity IDs like `sensor.car2home_toyota_corolla_cross_rpm`.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: Car2HomeCoordinator, sensor_id: str) -> None:
        super().__init__(coordinator)
        self._sensor_id = sensor_id

        data = coordinator.entry.data
        device_slug = data.get(CONF_DEVICE_SLUG) or build_base_slug(
            data.get(CONF_MANUFACTURER), data.get(CONF_MODEL)
        )
        vin = data.get(CONF_VIN)

        self._attr_unique_id = f"{device_slug}_{sensor_id}"

        # Slug is the primary, human-readable identifier. VIN (when present)
        # is kept as a secondary identifier so Device Registry deduplicates
        # across re-pair scenarios where the app connects with a different slug.
        identifiers = {(DOMAIN, device_slug)}
        if vin:
            identifiers.add((DOMAIN, f"vin:{vin}"))

        model = data.get(CONF_MODEL) or "Vehicle"
        self._attr_device_info = DeviceInfo(
            identifiers=identifiers,
            manufacturer=data.get(CONF_MANUFACTURER) or MANUFACTURER_DEFAULT,
            model=model,
            name=model,
            sw_version=data.get(CONF_SW_VERSION),
            hw_version=data.get(CONF_HW_VERSION),
        )

    @property
    def available(self) -> bool:
        # Always available — see module docstring.
        return True


def describe_from_frame(frame: dict[str, Any], platform: str) -> list[dict[str, Any]]:
    """Filter sensor descriptors from a hello frame by target platform."""
    sensors = (frame or {}).get("sensors") or []
    return [s for s in sensors if (s.get("platform") or "sensor") == platform]
