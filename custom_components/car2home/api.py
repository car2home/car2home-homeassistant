"""HTTP + WebSocket views for Car 2 Home.

Three endpoints:
  - POST /api/car2home/v1/pair    (ephemeral, auth via one-shot code)
  - GET  /api/car2home/v1/ws      (persistent bidirectional telemetry)
  - POST /api/car2home/v1/ingest  (stateless fallback for debug / scripts)

The pair view works WITHOUT HA auth while a pairing code is active; all others
require a token minted during pairing.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLIENT_ID,
    CONF_DEVICE_ID,
    CONF_DEVICE_SLUG,
    CONF_GARAGE_ID,
    CONF_HW_VERSION,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_NICKNAME,
    CONF_SW_VERSION,
    CONF_TARGETS,
    CONF_TOKEN,
    CONF_TOKENS,
    CONF_VIN,
    DOMAIN,
    FRAME_ACK,
    FRAME_AVAILABILITY,
    FRAME_BACKFILL,
    FRAME_ERROR,
    FRAME_EVENT,
    FRAME_HELLO,
    FRAME_LOCATION,
    FRAME_PING,
    FRAME_PONG,
    FRAME_STATE,
    HTTP_INGEST_PATH,
    PAIRING_CODE_DIGITS,
    PAIRING_CODE_TTL_SEC,
    PAIR_PATH,
    WIRE_PROTOCOL_VERSION,
    WS_PATH,
)
from .coordinator import Car2HomeCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class PendingPair:
    code: str
    created_at: float
    flow_id: str
    context: dict[str, Any] = field(default_factory=dict)
    result: asyncio.Future | None = None


class PairingManager:
    """Holds active pairing codes awaiting confirmation from the mobile app."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._pending: dict[str, PendingPair] = {}

    def start(self, flow_id: str, context: dict[str, Any]) -> str:
        code = "".join(
            secrets.choice("0123456789") for _ in range(PAIRING_CODE_DIGITS)
        )
        self._pending[code] = PendingPair(
            code=code,
            created_at=time.time(),
            flow_id=flow_id,
            context=context,
            result=self._hass.loop.create_future(),
        )
        return code

    def cancel(self, code: str) -> None:
        self._pending.pop(code, None)

    def prune(self) -> None:
        now = time.time()
        for code in list(self._pending.keys()):
            if now - self._pending[code].created_at > PAIRING_CODE_TTL_SEC:
                self._pending.pop(code, None)

    async def submit(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Called by the app POSTing the code. Returns token + ws_url.

        Also auto-advances the waiting HA ConfigFlow by calling
        ``async_configure(flow_id, {})`` — equivalent to the user clicking
        Submit on the pairing screen — so the HA UI transitions to success
        without requiring any click after the app confirms.
        """
        self.prune()
        pending = self._pending.get(code)
        if not pending:
            raise ValueError("invalid_or_expired_code")

        token = uuid.uuid4().hex + secrets.token_hex(16)
        ws_url = self._build_ws_url()
        entry_payload = {
            CONF_TOKEN: token,
            # VIN is empty at pair time (the ECU reports it later); do NOT fall
            # back to device_id here — that conflation made unique_id the model
            # slug and collided distinct cars. device_id is the stable car GUID.
            CONF_VIN: payload.get("vin"),
            CONF_DEVICE_ID: payload.get("device_id"),
            CONF_CLIENT_ID: payload.get("client_id"),
            CONF_NICKNAME: payload.get("nickname"),
            CONF_MANUFACTURER: payload.get("manufacturer"),
            CONF_MODEL: payload.get("model"),
            CONF_SW_VERSION: payload.get("sw_version"),
            CONF_HW_VERSION: payload.get("hw_version"),
            # Garage identity: acct_{sub} (signed in) or dev_{clientId}. Becomes
            # the config-entry unique_id so two phones of one account share it.
            CONF_GARAGE_ID: payload.get("garage_id"),
        }
        if pending.result and not pending.result.done():
            pending.result.set_result(entry_payload)
        flow_id = pending.flow_id
        self._pending.pop(code, None)

        # Auto-advance the waiting ConfigFlow. Fire-and-forget is fine:
        # if the flow isn't in the expected state, the call raises and we
        # log it, but the HTTP response to the app still goes through.
        async def _advance() -> None:
            try:
                await self._hass.config_entries.flow.async_configure(flow_id, {})
            except Exception as err:  # pragma: no cover - defensive
                _LOGGER.debug("Auto-advance of pairing flow failed: %s", err)

        self._hass.async_create_task(_advance())

        return {"status": "paired", "ws_url": ws_url, "token": token}

    async def wait_for(self, code: str, timeout: float) -> dict[str, Any]:
        pending = self._pending.get(code)
        if not pending or not pending.result:
            raise ValueError("no_pending_code")
        return await asyncio.wait_for(pending.result, timeout=timeout)

    def _build_ws_url(self) -> str:
        # Relative path; app combines with the HA URL it used to pair.
        return WS_PATH


class Car2HomePairView(HomeAssistantView):
    """Ephemeral POST endpoint that accepts a pairing code from the app."""

    url = PAIR_PATH
    name = "api:car2home:pair"
    requires_auth = False

    def __init__(self, pairing: PairingManager) -> None:
        self._pairing = pairing

    async def post(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)

        code = str(body.get("code") or "")
        if len(code) != PAIRING_CODE_DIGITS or not code.isdigit():
            return web.json_response({"error": "invalid_code_format"}, status=400)

        try:
            result = await self._pairing.submit(code, body)
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=401)

        return web.json_response(result)


def _find_coordinator_by_token(
    hass: HomeAssistant, token: str
) -> Car2HomeCoordinator | None:
    coord, _ = _resolve_token(hass, token)
    return coord


def _resolve_token(
    hass: HomeAssistant, token: str
) -> tuple[Car2HomeCoordinator | None, str | None]:
    """Resolve a token to its coordinator AND the paired phone's client_id.

    The client_id keys the per-phone WS registry so a garage shared by two
    phones keeps both sockets. Legacy single-token entries resolve to the
    ``"default"`` client_id. Doesn't early-exit on mismatch (uniform timing).
    """
    match: Car2HomeCoordinator | None = None
    match_client: str | None = None
    for entry_id, value in hass.data.get(DOMAIN, {}).items():
        if not isinstance(value, Car2HomeCoordinator):
            continue
        for client_id, candidate in (value.entry.data.get(CONF_TOKENS) or {}).items():
            if candidate and hmac.compare_digest(candidate, token):
                match = value
                match_client = client_id
        legacy = value.entry.data.get(CONF_TOKEN)
        if legacy and hmac.compare_digest(legacy, token):
            match = value
            match_client = match_client or "default"
    return match, match_client


class Car2HomeWsView(HomeAssistantView):
    """Persistent WebSocket for telemetry. Auth via ?token= query param."""

    url = WS_PATH
    name = "api:car2home:ws"
    requires_auth = False  # custom token check; not HA's auth system

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request) -> web.StreamResponse:
        token = request.query.get("token") or ""
        coord, client_id = _resolve_token(self._hass, token)
        if not coord:
            return web.Response(status=401, text="unauthorized")
        client_id = client_id or "default"

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        coord.set_ws_connected(True)
        # Register the live WS keyed by the paired phone's client_id. A garage
        # shared by two phones keeps BOTH sockets — a single slot would let one
        # phone overwrite the other's socket and drop its commands.
        registry = self._hass.data.setdefault(DOMAIN, {}).setdefault(
            f"_ws_{coord.entry.entry_id}", {}
        )
        registry[client_id] = ws
        _LOGGER.info(
            "car2home WS connected for entry %s (client %s)",
            coord.entry.entry_id, client_id,
        )

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_text(ws, coord, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    _LOGGER.warning("WS error: %s", ws.exception())
                    break
        finally:
            coord.set_ws_connected(False)
            # Remove only THIS phone's socket (identity check guards against a
            # reconnect race that already replaced our slot).
            reg = self._hass.data.get(DOMAIN, {}).get(f"_ws_{coord.entry.entry_id}")
            if reg is not None and reg.get(client_id) is ws:
                reg.pop(client_id, None)
            _LOGGER.info(
                "car2home WS disconnected for entry %s (client %s)",
                coord.entry.entry_id, client_id,
            )

        return ws

    async def _handle_text(
        self, ws: web.WebSocketResponse, coord: Car2HomeCoordinator, data: str
    ) -> None:
        try:
            frame = json.loads(data)
        except json.JSONDecodeError:
            await ws.send_json(
                {"type": FRAME_ERROR, "code": "invalid_json", "v": WIRE_PROTOCOL_VERSION}
            )
            return

        ftype = frame.get("type")
        if ftype == FRAME_PING:
            await ws.send_json(
                {
                    "type": FRAME_PONG,
                    "v": WIRE_PROTOCOL_VERSION,
                    "ts": int(time.time() * 1000),
                    "seq": frame.get("seq"),
                }
            )
            return

        if ftype == FRAME_HELLO:
            coord.handle_hello(frame)
        elif ftype == FRAME_STATE:
            coord.handle_state(frame)
        elif ftype == FRAME_LOCATION:
            coord.handle_location(frame)
        elif ftype == FRAME_BACKFILL:
            coord.handle_backfill(frame)
        elif ftype == FRAME_AVAILABILITY:
            coord.handle_availability(frame)
        elif ftype == FRAME_EVENT:
            # Fire on the HA event bus as `car2home_{event_name}`. Automations can
            # use `trigger: event, event_type: car2home_trip_ended` (etc.) and read
            # the payload from trigger.event.data.
            event_name = frame.get("event")
            if event_name:
                data = dict(frame.get("data") or {})
                # Attach the vehicle identity so automations can filter by car.
                # Resolve the event's target (car_id) against the target
                # catalogue; fall back to legacy single-device entry fields.
                target = str(frame.get("target") or data.get("car_id") or "")
                target_ctx = (coord.entry.data.get(CONF_TARGETS) or {}).get(target) or {}
                data.setdefault(
                    "vin", target_ctx.get("vin") or coord.entry.data.get(CONF_VIN)
                )
                data.setdefault(
                    "device_slug",
                    target_ctx.get("device_slug") or coord.entry.data.get(CONF_DEVICE_SLUG),
                )
                data.setdefault("timestamp_ms", frame.get("ts"))
                self._hass.bus.async_fire(f"{DOMAIN}_{event_name}", data)
        elif ftype == FRAME_ACK:
            pass
        else:
            await ws.send_json(
                {
                    "type": FRAME_ERROR,
                    "code": "unknown_type",
                    "v": WIRE_PROTOCOL_VERSION,
                    "received": ftype,
                }
            )


class Car2HomeIngestView(HomeAssistantView):
    """HTTP POST fallback: a single frame per request. Auth via Bearer token."""

    url = HTTP_INGEST_PATH
    name = "api:car2home:ingest"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def post(self, request: web.Request) -> web.Response:
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else request.query.get("token", "")
        coord = _find_coordinator_by_token(self._hass, token)
        if not coord:
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            frame = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)

        ftype = frame.get("type")
        if ftype == FRAME_HELLO:
            coord.handle_hello(frame)
        elif ftype == FRAME_STATE:
            coord.handle_state(frame)
        elif ftype == FRAME_LOCATION:
            coord.handle_location(frame)
        elif ftype == FRAME_BACKFILL:
            coord.handle_backfill(frame)
        elif ftype == FRAME_AVAILABILITY:
            coord.handle_availability(frame)
        else:
            return web.json_response({"error": "unknown_type"}, status=400)

        return web.json_response({"status": "ok"})
