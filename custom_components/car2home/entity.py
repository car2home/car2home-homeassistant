"""Base entity for Car 2 Home.

Key design choice (user requirement): data entities NEVER report unavailable.
Transport state is surfaced via a separate diagnostic binary_sensor
(`binary_sensor.*_ws_connected`), so lovelace cards that rely on historical
state keep rendering even after app/network outages.

Multi-car: every entity belongs to a TARGET (the garage hub, or one car). The
device identifier and unique_id are anchored on the immutable target id (the
car GUID, or the garage id) — never on the slug — so two cars of the same model
never collide and renaming a car never re-keys its entities. The slug only
feeds the human-readable device name / entity_id.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER_DEFAULT

_MANIFEST_VERSION = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
).get("version")
from .coordinator import Car2HomeCoordinator


class Car2HomeEntity(CoordinatorEntity[Car2HomeCoordinator]):
    """Shared entity base with DeviceInfo derived from a target context.

    unique_id convention: ``{target_id}_{sensor_id}`` where target_id is the
    immutable car GUID (or the garage id). Globally unique and stable.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Car2HomeCoordinator,
        target_ctx: dict[str, Any],
        sensor_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._sensor_id = sensor_id
        self._target_id = str(target_ctx.get("id"))

        model = target_ctx.get("model") or "Vehicle"
        nickname = target_ctx.get("nickname")

        self._attr_unique_id = f"{self._target_id}_{sensor_id}"

        # Device identity is the immutable target id ONLY. Never add the VIN as
        # a secondary identifier: HA's device registry MERGES devices that share
        # any identifier, and two car profiles can legitimately carry the same
        # VIN (e.g. two profiles connected to the same physical car during
        # testing, or a VIN stamped onto the wrong active profile). That merge
        # collapsed two cars into one device in the wild. VIN stays available in
        # the target catalogue for event enrichment.
        identifiers = {(DOMAIN, self._target_id)}

        # Fold the nickname into the device name so two cars of the same model
        # show as "Corolla Cross · Meu" / "· Esposa" instead of two identical
        # "Corolla Cross" devices.
        name = target_ctx.get("name") or (f"{model} · {nickname}" if nickname else model)
        self._attr_device_info = DeviceInfo(
            identifiers=identifiers,
            manufacturer=target_ctx.get("manufacturer") or MANUFACTURER_DEFAULT,
            model=model,
            name=name,
            sw_version=_MANIFEST_VERSION,
        )

    def _values(self) -> dict[str, Any]:
        """This target's value namespace. Defensive .get chain — never index
        ``values[target][id]`` (a KeyError on the first frame propagates up
        through the aiohttp WS handler and tears the socket down)."""
        return self.coordinator.data.get("values", {}).get(self._target_id, {}) or {}

    @property
    def available(self) -> bool:
        # Always available — see module docstring.
        return True


def iter_target_descriptors(data: dict[str, Any], platform: str):
    """Yield ``(target_ctx, descriptor)`` for every sensor of the given platform
    across all targets (garage hub + cars)."""
    for ctx in (data or {}).get("targets", {}).values():
        for s in ctx.get("sensors") or []:
            if (s.get("platform") or "sensor") == platform:
                yield ctx, s
