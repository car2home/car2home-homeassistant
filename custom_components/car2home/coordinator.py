"""Data coordinator for Car 2 Home: push-based, never marks unavailable.

Multi-car ("garage") model: one config entry is one garage. Under it live N
"targets" — one stable garage-hub target (phone/connection meta) plus one target
per car. Every target is an independent HA device. State/location values are
namespaced by target id so two cars sharing a bare sensor id (e.g. two
``month_fuel_cost`` or two ``010C``) never collide.

``data`` shape::

    {
      "targets":  { target_id: {kind, id, device_slug, model, manufacturer,
                                nickname, vin, is_primary, name, sensors:[...]} },
      "values":   { target_id: { sensor_id: value } },
      "location": { target_id: {frame} },
      "ws_connected": bool,
      "last_frame_ts": float,
    }
"""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_GARAGE_ID,
    CONF_TARGETS,
    DOMAIN,
    MANUFACTURER_DEFAULT,
    SIGNAL_AVAILABILITY,
    SIGNAL_LOCATION,
    SIGNAL_NEW_DESCRIPTOR,
    SIGNAL_STATE_UPDATE,
    TARGET_KIND_CAR,
    TARGET_KIND_GARAGE,
)

_LOGGER = logging.getLogger(__name__)


class Car2HomeCoordinator(DataUpdateCoordinator):
    """Push-only coordinator; data flows in via WS frames, never polled."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=None,
            # MUST be True. We mutate `self.data` in place and pass the same
            # reference to async_set_updated_data every frame. With
            # always_update=False, HA compares `data == self.data` and finds
            # reference equality on the SAME dict, skipping listener dispatch.
            # The app already de-duplicates at the wire level (delta-only in
            # HaSyncService.FlushPendingAsync), so letting HA always dispatch
            # here doesn't cause extra traffic — only cheap listener calls.
            always_update=True,
        )
        self.entry = entry
        self.data: dict[str, Any] = {
            "targets": {},
            "values": {},
            "location": {},
            "ws_connected": False,
            "last_frame_ts": 0.0,
        }

    async def async_setup(self) -> None:
        """Seed targets from the config entry so built-in entities (the garage
        hub's ws_connected / sync-mode switch) can attach before the first
        hello arrives."""
        for target_id, ctx in (self.entry.data.get(CONF_TARGETS) or {}).items():
            self.data["targets"][target_id] = {**ctx, "sensors": ctx.get("sensors") or []}

        # Prime the coordinator with an initial update so `last_update_success`
        # flips to True; otherwise every entity starts `unavailable`.
        self.async_set_updated_data(self.data)

    async def async_shutdown(self) -> None:
        """Release resources. Nothing persistent; the view holds the WS."""

    # ── target helpers ───────────────────────────────────────────────────────

    def garage_id(self) -> str | None:
        gid = self.entry.data.get(CONF_GARAGE_ID)
        if gid:
            return gid
        for tid, ctx in self.data.get("targets", {}).items():
            if ctx.get("kind") == TARGET_KIND_GARAGE:
                return tid
        return None

    def garage_ctx(self) -> dict[str, Any]:
        """The garage-hub target context. Synthesised if no hello has landed
        yet so the built-in ws_connected / switch entities still get a device."""
        gid = self.garage_id()
        if gid and gid in self.data.get("targets", {}):
            return self.data["targets"][gid]
        gid = gid or self.entry.entry_id
        return {
            "kind": TARGET_KIND_GARAGE,
            "id": gid,
            "device_slug": f"car2home_garage_{gid}",
            "model": "Garage",
            "manufacturer": MANUFACTURER_DEFAULT,
            "name": "Car 2 Home",
            "nickname": None,
            "vin": None,
            "sensors": [],
        }

    # ── frame handlers ───────────────────────────────────────────────────────

    @callback
    def handle_hello(self, frame: dict[str, Any]) -> None:
        """Install/refresh per-target descriptors from a v2 hello.

        v2 hello carries ``garage`` (one) + ``cars`` (N). Each becomes a target.
        Persist the target catalogue to entry.data so devices survive a restart
        and event enrichment (api.py) can resolve a car's slug/vin offline.
        """
        changed = False
        garage = frame.get("garage")
        if isinstance(garage, dict) and garage.get("id"):
            changed |= self._upsert_target(TARGET_KIND_GARAGE, garage.get("id"), garage)

        for car in frame.get("cars") or []:
            if isinstance(car, dict) and car.get("car_id"):
                changed |= self._upsert_target(TARGET_KIND_CAR, car.get("car_id"), car)

        self.data["last_frame_ts"] = time.time()
        self.data["ws_connected"] = True
        self.async_set_updated_data(self.data)
        async_dispatcher_send(self.hass, SIGNAL_NEW_DESCRIPTOR, self.entry.entry_id)
        if changed:
            self._persist_targets()

    def _upsert_target(self, kind: str, target_id: str, block: dict[str, Any]) -> bool:
        """Store a target's meta + sensors. Returns True if the persisted meta
        changed (so we only rewrite entry.data when something relevant moved)."""
        target_id = str(target_id)
        existing = self.data["targets"].get(target_id) or {}
        ctx = {
            "kind": kind,
            "id": target_id,
            "device_slug": block.get("device_slug") or existing.get("device_slug"),
            "model": block.get("model") or existing.get("model"),
            "manufacturer": block.get("manufacturer") or existing.get("manufacturer"),
            "nickname": block.get("nickname", existing.get("nickname")),
            "vin": (block.get("vin") or existing.get("vin") or "").strip() or None,
            "is_primary": block.get("is_primary", existing.get("is_primary")),
            "name": block.get("name") or existing.get("name"),
            "sensors": block.get("sensors") or [],
            # Sensors the app is explicitly NOT exporting. Kept per target so each platform can delete
            # the matching entities instead of leaving them frozen at their last value.
            "retired_sensors": block.get("retired_sensors") or [],
        }
        self.data["targets"][target_id] = ctx
        # Compare only the persisted (non-sensor) meta to decide on a rewrite.
        meta_keys = ("kind", "device_slug", "model", "manufacturer", "nickname", "vin", "is_primary", "name")
        return any(existing.get(k) != ctx.get(k) for k in meta_keys)

    def _persist_targets(self) -> None:
        """Persist the target catalogue (meta only, no sensor lists) so a HA
        restart rebuilds devices and event enrichment works without a live WS.
        Does NOT reload the entry (a reload would orphan the open socket).

        Merges OVER the persisted catalogue instead of replacing it, so a car a
        second phone just linked via config_flow (written to entry.data but not
        yet in this live coordinator's in-memory view) is not dropped when this
        phone's hello triggers a persist first."""
        catalogue = dict(self.entry.data.get(CONF_TARGETS) or {})
        for tid, ctx in self.data["targets"].items():
            catalogue[tid] = {k: v for k, v in ctx.items() if k != "sensors"}
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_TARGETS: catalogue}
        )

    @callback
    def handle_state(self, frame: dict[str, Any]) -> None:
        """Apply a delta state update to the frame's target namespace."""
        target = str(frame.get("target") or self.garage_id() or "")
        values = frame.get("values") or {}
        if not target:
            return
        self.data["values"].setdefault(target, {}).update(values)
        self.data["last_frame_ts"] = time.time()
        self.data["ws_connected"] = True
        self.async_set_updated_data(self.data)
        async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATE, self.entry.entry_id)

    @callback
    def handle_backfill(self, frame: dict[str, Any]) -> None:
        """Replay buffered frames into a target namespace; last-value-wins."""
        target = str(frame.get("target") or self.garage_id() or "")
        if not target:
            return
        frames = frame.get("frames") or []
        merged: dict[str, Any] = {}
        for f in frames:
            if isinstance(f, dict):
                merged.update(f.get("values") or {})
        if merged:
            self.data["values"].setdefault(target, {}).update(merged)
            self.async_set_updated_data(self.data)

    @callback
    def handle_location(self, frame: dict[str, Any]) -> None:
        """Phone GPS is a garage-hub concern; store under the frame's target
        (the garage id) so the device_tracker on the garage device reads it."""
        target = str(frame.get("target") or self.garage_id() or "")
        if not target:
            return
        self.data["location"][target] = frame
        self.data["last_frame_ts"] = time.time()
        self.async_set_updated_data(self.data)
        async_dispatcher_send(self.hass, SIGNAL_LOCATION, self.entry.entry_id)

    @callback
    def handle_availability(self, frame: dict[str, Any]) -> None:
        """ECU availability is surfaced via a diagnostic binary_sensor only;
        data entities never go unavailable (see entity.py)."""
        self.data.setdefault("availability", {})["ecu"] = frame.get("state")
        self.async_set_updated_data(self.data)
        async_dispatcher_send(self.hass, SIGNAL_AVAILABILITY, self.entry.entry_id)

    @callback
    def set_ws_connected(self, connected: bool) -> None:
        self.data["ws_connected"] = connected
        self.async_set_updated_data(self.data)
        async_dispatcher_send(self.hass, SIGNAL_AVAILABILITY, self.entry.entry_id)
