"""Binary sensor platform for Car 2 Home.

Includes a built-in diagnostic binary_sensor `ws_connected` that reflects the
WebSocket transport state — this is the ONE entity allowed to flip off when
the app disconnects. All data entities stay available (see entity.py).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_NEW_DESCRIPTOR
from .coordinator import Car2HomeCoordinator
from .entity import Car2HomeEntity, describe_from_frame


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Car2HomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    async_add_entities([WsConnectedSensor(coordinator)])

    @callback
    def _add_from_descriptor(entry_id: str | None = None) -> None:
        if entry_id is not None and entry_id != coordinator.entry.entry_id:
            return
        descriptor = coordinator.data.get("descriptor")
        if not descriptor:
            return
        new_entities: list[Car2HomeBinarySensor] = []
        for desc in describe_from_frame(descriptor, "binary_sensor"):
            sensor_id = desc.get("id")
            if not sensor_id or sensor_id in known:
                continue
            known.add(sensor_id)
            new_entities.append(Car2HomeBinarySensor(coordinator, desc))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_DESCRIPTOR, _add_from_descriptor)
    )
    _add_from_descriptor()


class Car2HomeBinarySensor(Car2HomeEntity, BinarySensorEntity):
    def __init__(
        self, coordinator: Car2HomeCoordinator, desc: dict[str, Any]
    ) -> None:
        super().__init__(coordinator, desc["id"])
        self._desc = desc
        self._attr_name = desc.get("name")
        self._attr_translation_key = desc.get("translation_key")
        self._attr_icon = desc.get("icon")
        self._attr_device_class = None
        device_class = desc.get("device_class")
        if device_class:
            try:
                self._attr_device_class = BinarySensorDeviceClass(device_class)
            except ValueError:
                pass
        if desc.get("entity_category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get("values", {}).get(self._sensor_id)
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("on", "true", "1", "online", "yes")
        if isinstance(value, (int, float)):
            return value != 0
        return None


class WsConnectedSensor(Car2HomeEntity, BinarySensorEntity):
    """Diagnostic binary sensor: WS transport up/down. This one CAN flip off."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "ws_connected"
    _attr_name = "Connection"

    def __init__(self, coordinator: Car2HomeCoordinator) -> None:
        super().__init__(coordinator, "ws_connected")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("ws_connected", False))

    # No extra SIGNAL_AVAILABILITY listener — we inherit CoordinatorEntity and
    # the coordinator already calls async_set_updated_data() whenever ws_connected
    # flips, which in turn triggers _handle_coordinator_update → async_write_ha_state
    # on the event loop (thread-safe). The earlier dispatcher lambda bypassed
    # that path and was dispatched on a thread other than the event loop, which
    # HA 2026 flags as an error.
