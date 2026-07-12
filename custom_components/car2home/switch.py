"""Switch platform for Car 2 Home.

Exposes a single `switch.*_sync_mode_online` entity:
  - ON  → app runs in Online mode (live telemetry during the trip).
  - OFF → app runs in Home mode (buffers locally, flushes on home Wi-Fi).

Toggling the switch sends a `command` frame back to the mobile app over the
persistent WebSocket; the app updates its own SyncMode and echoes the new
value back as a `sync_mode` state update, which keeps this switch in sync
with the app's source of truth.
"""
from __future__ import annotations

import json
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_STATE_UPDATE
from .coordinator import Car2HomeCoordinator
from .entity import Car2HomeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Car2HomeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Car2HomeSyncModeSwitch(coordinator)])


class Car2HomeSyncModeSwitch(Car2HomeEntity, SwitchEntity):
    """Switch Online ⇄ Home for the paired app."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "sync_mode_online"
    _attr_icon = "mdi:cloud-sync-outline"
    _attr_name = "Online sync mode"

    def __init__(self, coordinator: Car2HomeCoordinator) -> None:
        # Sync mode is a phone/garage concern, not per-car → garage-hub device.
        super().__init__(coordinator, coordinator.garage_ctx(), "sync_mode_online")

    @property
    def is_on(self) -> bool:
        # App echoes sync_mode as a state value ("online" / "home") in the
        # garage-hub namespace. Default to True (Online) so HA renders a sane
        # initial state while the first hello frame hasn't arrived yet.
        v = self._values().get("sync_mode")
        if isinstance(v, str):
            return v.lower() != "home"
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send_cmd("set_sync_mode_online")
        self._optimistic("online")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send_cmd("set_sync_mode_home")
        self._optimistic("home")

    def _optimistic(self, mode: str) -> None:
        # Optimistic local update in THIS target's namespace; the app's state
        # echo will confirm. A flat write would land where nothing reads it.
        self.coordinator.data.setdefault("values", {}).setdefault(
            self._target_id, {}
        )["sync_mode"] = mode
        self.async_write_ha_state()

    async def _send_cmd(self, cmd: str) -> None:
        """Push a server→client command to every phone paired to this garage.

        The registry holds one socket per paired phone (keyed by client_id), so
        a garage shared by two phones gets the toggle on both. The app's
        HaService routes it to HaSyncService.OnHaCommandReceived.
        """
        domain_data = self.hass.data.get(DOMAIN, {})
        sockets = domain_data.get(f"_ws_{self.coordinator.entry.entry_id}") or {}
        payload = json.dumps({"type": "command", "v": 2, "cmd": cmd})
        for ws in list(sockets.values()):
            if ws is None or ws.closed:
                continue
            try:
                await ws.send_str(payload)
            except Exception:  # pragma: no cover - defensive, ws may race-close
                pass

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_STATE_UPDATE,
                self._on_state_update,
            )
        )

    @callback
    def _on_state_update(self, entry_id: str) -> None:
        if entry_id == self.coordinator.entry.entry_id:
            self.async_write_ha_state()
