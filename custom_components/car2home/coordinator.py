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
