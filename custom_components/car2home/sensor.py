"""Sensor platform for Car 2 Home."""
from __future__ import annotations

from datetime import date, datetime
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
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_NEW_DESCRIPTOR
from .coordinator import Car2HomeCoordinator
from .entity import Car2HomeEntity, iter_target_descriptors, reap_retired_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Car2HomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Keyed by (target_id, sensor_id): the same bare sensor id can legitimately
    # exist on more than one car device.
    known: set[tuple[str, str]] = set()

    @callback
    def _add_from_descriptor(entry_id: str | None = None) -> None:
        # Dispatcher broadcasts to every registered listener; filter out events
        # meant for a different config entry (multi-vehicle installs).
        if entry_id is not None and entry_id != coordinator.entry.entry_id:
            return
        new_entities: list[Car2HomeSensor] = []
        for target_ctx, desc in iter_target_descriptors(coordinator.data, "sensor"):
            sensor_id = desc.get("id")
            key = (str(target_ctx.get("id")), sensor_id)
            if not sensor_id or key in known:
                continue
            known.add(key)
            new_entities.append(Car2HomeSensor(coordinator, target_ctx, desc))
        # Retire BEFORE adding. An id that moved (the app renamed a sensor, restored its English
        # text, or a sibling changed its key) arrives as old id in retired_sensors and new id in
        # sensors, in the SAME frame. Removing the old registry entry first frees its entity_id,
        # so the new entity inherits it and history and automations carry on. The other way
        # round, every rename minted a "_2" twin next to a dead original.
        reap_retired_entities(hass, coordinator.data, "sensor", known)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_DESCRIPTOR, _add_from_descriptor)
    )
    _add_from_descriptor()


class Car2HomeSensor(Car2HomeEntity, RestoreSensor, SensorEntity):
    """Dynamic sensor created from the app's descriptor."""

    def __init__(
        self, coordinator: Car2HomeCoordinator, target_ctx: dict[str, Any], desc: dict[str, Any]
    ) -> None:
        super().__init__(coordinator, target_ctx, desc["id"])
        self._desc = desc
        self._attr_name = desc.get("name")
        self._attr_translation_key = desc.get("translation_key")
        if desc.get("entity_category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._apply_descriptor(desc)

    def _apply_descriptor(self, desc: dict[str, Any]) -> None:
        """Take the unit, icon, device and state class, precision and options of a descriptor.

        Called at creation and again whenever the app declares this sensor differently (the person changed the
        unit of a measure Home Assistant cannot convert, such as fuel economy): a value arriving in the new unit
        must never be shown under the unit the entity was created with. The name is set at creation only, since
        the person may have renamed the entity in Home Assistant.
        """
        self._desc = desc
        self._attr_icon = desc.get("icon")
        self._attr_native_unit_of_measurement = desc.get("unit") or None

        # Always assign both, so a descriptor without them never leaves an attribute unset (an unset device
        # class once crashed sensor creation and closed the socket).
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
        self._attr_suggested_display_precision = (
            precision if isinstance(precision, int) and has_numeric_context else None
        )

        # ENUM is a non-numeric device_class even though it sets a "context"
        # — exclude it from the numeric guard in native_value below.
        self._numeric_required = (
            has_numeric_context
            and self._attr_device_class != SensorDeviceClass.ENUM
        )

        # None unless this is an enum with declared options, so the defensive check in native_value always works.
        self._attr_options = None
        options = desc.get("options")
        if options and self._attr_device_class == SensorDeviceClass.ENUM:
            self._attr_options = list(options)

    def _follow_declared_descriptor(self) -> None:
        """Adopt the descriptor the app declares now for this sensor, when it differs from the one applied."""
        target = (self.coordinator.data.get("targets") or {}).get(self._target_id) or {}
        for desc in target.get("sensors") or []:
            if desc.get("id") == self._sensor_id:
                if desc != self._desc:
                    previous_unit = self._attr_native_unit_of_measurement
                    self._apply_descriptor(desc)
                    if self._attr_native_unit_of_measurement != previous_unit:
                        # The value held now was sent in the previous unit; under the new label it would read as a
                        # wrong number (8.1 L/100km shown as 8.1 km/L). Show unknown until the app sends one in the
                        # new unit.
                        self._values().pop(self._sensor_id, None)
                return

    @callback
    def _handle_coordinator_update(self) -> None:
        # Before the state is written, so the unit and the value of one write always agree (a hello that changes
        # the unit and the values in the new unit reach the entity in the same update).
        self._follow_declared_descriptor()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The catalogue may already hold a newer descriptor than the one this entity was built from.
        self._follow_declared_descriptor()
        last = await self.async_get_last_sensor_data()
        # A value saved under another unit (the app changed it while Home Assistant was down) is not restored, for
        # the same reason a held value is dropped when the unit changes.
        if (
            last is not None
            and last.native_value is not None
            and last.native_unit_of_measurement == self._attr_native_unit_of_measurement
        ):
            # Seed the restored value into THIS target's namespace so the first
            # render isn't None. Must nest under _target_id — a flat write would
            # land outside every car namespace and never be read.
            self.coordinator.data.setdefault("values", {}).setdefault(
                self._target_id, {}
            ).setdefault(self._sensor_id, last.native_value)

    @property
    def native_value(self) -> Any:
        value = self._values().get(self._sensor_id)
        # Empty string is a common intermediate state for OBD text sensors
        # before the bitmask validates — returning it as-is makes HA try to
        # coerce to numeric (depending on device_class/state_class) and raise
        # ValueError. Surface as None = unknown instead.
        if isinstance(value, str) and not value:
            return None

        # A `timestamp` device_class sensor MUST return a tz-aware datetime
        # object — HA rejects a raw ISO string and shows "unknown" (this is why
        # "Last refuel — Date" was blank). Parse the app's ISO-8601 string
        # (e.g. "2026-06-16T21:00:00.0000000Z") into a datetime.
        if self._attr_device_class == SensorDeviceClass.TIMESTAMP:
            if isinstance(value, str):
                parsed = dt_util.parse_datetime(value)
                # A value without a time zone is rejected by Home Assistant and would abort the write: unknown.
                return parsed if parsed is not None and parsed.tzinfo is not None else None
            if isinstance(value, datetime) and value.tzinfo is None:
                return None
            return value

        # A `date` device_class sensor MUST return a date object, never a string: HA rejects a raw "2026-12-06". A
        # value restored from the time this entity was a timestamp (a datetime) keeps its day.
        if self._attr_device_class == SensorDeviceClass.DATE:
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            if isinstance(value, str):
                day = dt_util.parse_date(value)
                if day is None:
                    parsed = dt_util.parse_datetime(value)
                    day = parsed.date() if parsed is not None else None
                return day
            return None

        # Defense in depth: a sensor with numeric context (state_class set,
        # numeric device_class, or a unit) MUST publish numeric values — HA
        # raises ValueError mid-render otherwise, which propagates up through
        # the WS view's finally block and tears the socket down (same failure
        # mode the precision comment in __init__ describes). Happens in the
        # wild when a descriptor declares state_class: measurement on a sensor
        # that actually publishes text — e.g. sensor.corolla_cross_injection
        # sending OBD enum labels like 'Direct' / 'Both'. Surface as unknown
        # so the transport survives; the descriptor itself should be fixed
        # app-side, but this keeps a misconfigured sensor from taking down
        # every other entity on the same WS.
        if isinstance(value, str) and self._numeric_required:
            try:
                return float(value)
            except (TypeError, ValueError):
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
