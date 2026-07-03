"""Data coordinator for Car 2 Home: push-based, never marks unavailable."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_NICKNAME,
    CONF_VIN,
    DOMAIN,
    SIGNAL_AVAILABILITY,
    SIGNAL_LOCATION,
    SIGNAL_NEW_DESCRIPTOR,
    SIGNAL_STATE_UPDATE,
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
            # Result in the wild: sensors get initial values on first frame
            # (when internal self.data was None) and then never update again.
            # The app already de-duplicates at the wire level (delta-only in
            # HaSyncService.FlushPendingAsync), so letting HA always dispatch
            # here doesn't cause extra traffic — only unnecessary listener
            # calls, which is cheap.
            always_update=True,
        )
        self.entry = entry
        self.data: dict[str, Any] = {
            "values": {},
            "location": None,
            "descriptor": None,
            "ws_connected": False,
            "last_frame_ts": 0.0,
        }

    async def async_setup(self) -> None:
        """Initialize any pre-connection state from config entry."""
        # Descriptor may be rebuilt from the first hello after (re)start.
        self.data["descriptor"] = self.entry.data.get("descriptor")

        # Prime the coordinator with an initial update so `last_update_success`
        # flips to True. Without this, every entity starts in `unavailable`
        # state (which shows up as "Connection ficou indisponível" in the HA
        # activity feed). After priming, `binary_sensor.*_connection` shows as
        # `off` — the intended "disconnected but responsive" state.
        self.async_set_updated_data(self.data)

    async def async_shutdown(self) -> None:
        """Release resources. Nothing persistent; the view holds the WS."""

    @callback
    def handle_hello(self, frame: dict[str, Any]) -> None:
        """Process a hello frame: install/refresh the sensor descriptor."""
        self.data["descriptor"] = frame
        self.data["last_frame_ts"] = time.time()
        self.data["ws_connected"] = True
        self.async_set_updated_data(self.data)
        async_dispatcher_send(self.hass, SIGNAL_NEW_DESCRIPTOR, self.entry.entry_id)
        self._maybe_adopt_device_info(frame)

    @callback
    def _maybe_adopt_device_info(self, frame: dict[str, Any]) -> None:
        """Fold in device details only known after the ECU connects.

        - VIN: empty at pair time; once reported, store it (entity.py adds the
          ``vin:`` secondary identifier on the next entry setup).
        - Nickname: store a rename.

        Only PERSISTS to entry.data — it does NOT reload the entry. A live
        WebSocket is bound to THIS coordinator instance (api.py resolves the
        coordinator once and dispatches every frame to it); reloading would
        unload this coordinator, orphan the still-open socket, and rebuild a
        coordinator with no descriptor (zero entities). The refreshed device name
        / vin identifier therefore take effect on the next natural entry setup
        (HA restart or manual reload), which is fine — the nickname is already
        applied at pair time and the VIN identifier is only a dedup nicety.
        unique_id (the car GUID) is never touched, so no collision is possible.
        """
        device = frame.get("device") or {}
        updates: dict[str, Any] = {}
        vin = (device.get("vin") or "").strip()
        if vin and vin != (self.entry.data.get(CONF_VIN) or ""):
            updates[CONF_VIN] = vin
        nickname = (device.get("nickname") or "").strip()
        if nickname and nickname != (self.entry.data.get(CONF_NICKNAME) or ""):
            updates[CONF_NICKNAME] = nickname
        if not updates:
            return
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, **updates}
        )

    @callback
    def handle_state(self, frame: dict[str, Any]) -> None:
        """Apply a delta state update."""
        values = frame.get("values") or {}
        self.data["values"].update(values)
        self.data["last_frame_ts"] = time.time()
        self.data["ws_connected"] = True
        self.async_set_updated_data(self.data)
        async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATE, self.entry.entry_id)

    @callback
    def handle_backfill(self, frame: dict[str, Any]) -> None:
        """Replay buffered frames; last-value-wins semantics in HA state."""
        frames = frame.get("frames") or []
        merged: dict[str, Any] = {}
        for f in frames:
            if isinstance(f, dict):
                merged.update(f.get("values") or {})
        if merged:
            self.data["values"].update(merged)
            self.async_set_updated_data(self.data)

    @callback
    def handle_location(self, frame: dict[str, Any]) -> None:
        self.data["location"] = frame
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
