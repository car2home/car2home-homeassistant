"""Device tracker platform for Car 2 Home — GPS source."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_LOCATION, SIGNAL_NEW_DESCRIPTOR
from .coordinator import Car2HomeCoordinator
from .entity import Car2HomeEntity, iter_target_descriptors, reap_retired_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Car2HomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[tuple[str, str]] = set()

    @callback
    def _add_from_descriptor(entry_id: str | None = None) -> None:
        if entry_id is not None and entry_id != coordinator.entry.entry_id:
            return
        new_entities: list[Car2HomeTracker] = []
        for target_ctx, desc in iter_target_descriptors(coordinator.data, "device_tracker"):
            sensor_id = desc.get("id")
            key = (str(target_ctx.get("id")), sensor_id)
            if not sensor_id or key in known:
                continue
            known.add(key)
            new_entities.append(Car2HomeTracker(coordinator, target_ctx, sensor_id, desc))
        if new_entities:
            async_add_entities(new_entities)
        # Same pass removes what the app stopped exporting — an entity left behind would sit at its
        # last value forever, which is worse than never having created it.
        reap_retired_entities(hass, coordinator.data, "device_tracker", known)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_DESCRIPTOR, _add_from_descriptor)
    )
    _add_from_descriptor()


class Car2HomeTracker(Car2HomeEntity, TrackerEntity):
    _attr_source_type = SourceType.GPS

    def __init__(
        self,
        coordinator: Car2HomeCoordinator,
        target_ctx: dict,
        sensor_id: str,
        desc: dict,
    ) -> None:
        super().__init__(coordinator, target_ctx, sensor_id)
        self._attr_name = desc.get("name") or "Phone"
        self._attr_translation_key = desc.get("translation_key") or sensor_id

    def _loc(self) -> dict:
        # Phone GPS is stored under this target's namespace (the garage hub).
        return self.coordinator.data.get("location", {}).get(self._target_id) or {}

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
