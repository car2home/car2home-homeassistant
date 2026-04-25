"""Sensor platform for Car 2 Home."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
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

    @callback
    def _add_from_descriptor(entry_id: str | None = None) -> None:
        # Dispatcher broadcasts to every registered listener; filter out events
        # meant for a different config entry (multi-vehicle installs).
        if entry_id is not None and entry_id != coordinator.entry.entry_id:
            return
        descriptor = coordinator.data.get("descriptor")
        if not descriptor:
            return
        new_entities: list[Car2HomeSensor] = []
        for desc in describe_from_frame(descriptor, "sensor"):
            sensor_id = desc.get("id")
            if not sensor_id or sensor_id in known:
                continue
            known.add(sensor_id)
            new_entities.append(Car2HomeSensor(coordinator, desc))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_DESCRIPTOR, _add_from_descriptor)
    )
    _add_from_descriptor()


class Car2HomeSensor(Car2HomeEntity, RestoreSensor, SensorEntity):
    """Dynamic sensor created from the app's descriptor."""

    def __init__(
        self, coordinator: Car2HomeCoordinator, desc: dict[str, Any]
    ) -> None:
        super().__init__(coordinator, desc["id"])
        self._desc = desc
        self._attr_name = desc.get("name")
        self._attr_translation_key = desc.get("translation_key")
        self._attr_icon = desc.get("icon")
        self._attr_native_unit_of_measurement = desc.get("unit") or None

        # Always initialize these so later reads (e.g. the options-vs-enum
        # check below) don't hit AttributeError when the descriptor omits
        # device_class / state_class. Previously, if `device_class` wasn't
        # set, `self._attr_device_class` stayed unassigned and the `if options
        # and self._attr_device_class == ...` line crashed — which aborted
        # sensor creation and also closed the WS as a side effect.
        self._attr_device_class = None
        self._attr_state_class = None

        device_class = desc.get("device_class")
        if device_class:
            try:
                self._attr_device_class = SensorDeviceClass(device_class)
            except ValueError:
                pass

        state_class = desc.get("state_class")
        if state_class:
            try:
                self._attr_state_class = SensorStateClass(state_class)
            except ValueError:
                pass

        if desc.get("entity_category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Only apply precision when the sensor has a numeric context (device
        # class that HA recognizes as numeric, a state_class, or a unit). HA
        # treats "suggested_display_precision set + no unit/class" as "this
        # sensor MUST be numeric", which makes the first render explode if
        # the value happens to be a string (OBD text enums like Fuel System
        # Status publish '' before the bitmask validates). Once it explodes,
        # the exception propagates up to set_ws_connected(False) in the view's
        # finally block and tears down the WS — causing the reconnect storm
        # seen in the wild.
        precision = desc.get("precision")
        has_numeric_context = bool(
            self._attr_device_class
            or self._attr_state_class
            or self._attr_native_unit_of_measurement
        )
        if isinstance(precision, int) and has_numeric_context:
            self._attr_suggested_display_precision = precision

        # Initialize to None so the defensive check in native_value works even
        # when the descriptor doesn't declare options / this isn't an enum.
        self._attr_options = None
        options = desc.get("options")
        if options and self._attr_device_class == SensorDeviceClass.ENUM:
            self._attr_options = list(options)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value is not None:
            # Seed coordinator with restored value so first render isn't None.
            self.coordinator.data.setdefault("values", {}).setdefault(
                self._sensor_id, last.native_value
            )

    @property
    def native_value(self) -> Any:
        value = self.coordinator.data.get("values", {}).get(self._sensor_id)
        # Empty string is a common intermediate state for OBD text sensors
        # before the bitmask validates — returning it as-is makes HA try to
        # coerce to numeric (depending on device_class/state_class) and raise
        # ValueError. Surface as None = unknown instead.
        if isinstance(value, str) and not value:
            return None

        # Defense in depth: for enum sensors, a value outside the declared
        # options list makes HA raise ValueError during render; that exception
        # propagates up through the aiohttp WS handler and closes the socket,
        # triggering a reconnect storm. Happened in the wild when the app sent
        # localized enum labels (e.g. "Etanol") while the options list had the
        # English labels from the profile JSON. The app side is now authoritative
        # (sends the English label), but treat any options-mismatch as unknown
        # here so a future regression never takes down the transport.
        if (
            self._attr_device_class == SensorDeviceClass.ENUM
            and self._attr_options is not None
            and value is not None
            and value not in self._attr_options
        ):
            return None

        return value
