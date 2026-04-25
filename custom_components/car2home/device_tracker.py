"""Device tracker platform for Car 2 Home — GPS source."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_LOCATION, SIGNAL_NEW_DESCRIPTOR
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
        if entry_id is not None and entry_id != coordinator.entry.entry_id:
            return
        descriptor = coordinator.data.get("descriptor")
        if not descriptor:
            return
        new_entities: list[Car2HomeTracker] = []
        for desc in describe_from_frame(descriptor, "device_tracker"):
            sensor_id = desc.get("id")
            if not sensor_id or sensor_id in known:
                continue
            known.add(sensor_id)
            new_entities.append(Car2HomeTracker(coordinator, sensor_id, desc))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_DESCRIPTOR, _add_from_descriptor)
    )
    _add_from_descriptor()


class Car2HomeTracker(Car2HomeEntity, TrackerEntity):
    _attr_source_type = SourceType.GPS

    def __init__(
        self,
        coordinator: Car2HomeCoordinator,
        sensor_id: str,
        desc: dict,
    ) -> None:
        super().__init__(coordinator, sensor_id)
        self._attr_name = desc.get("name") or "Phone"
        self._attr_translation_key = desc.get("translation_key") or sensor_id

    def _loc(self) -> dict:
        return self.coordinator.data.get("location") or {}

    @property
    def latitude(self) -> float | None:
        return self._loc().get("latitude")

    @property
    def longitude(self) -> float | None:
        return self._loc().get("longitude")

    @property
    def location_accuracy(self) -> int:
        acc = self._loc().get("gps_accuracy")
        try:
            return int(acc) if acc is not None else 0
        except (TypeError, ValueError):
            return 0

    @property
    def battery_level(self) -> int | None:
        bl = self._loc().get("battery_level")
        try:
            return int(bl) if bl is not None else None
        except (TypeError, ValueError):
            return None
