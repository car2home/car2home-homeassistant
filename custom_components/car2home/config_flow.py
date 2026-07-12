"""Config flow for Car 2 Home.

Flow UX (zero-click for the user on the Home Assistant side):

    1. User clicks "Add Integration → Car 2 Home".
    2. HA shows a single form with a large 6-digit code and step-by-step
       instructions. The schema is empty — there is nothing to type here.
    3. The user goes to the mobile app and types the code.
    4. When the app POSTs the code to /api/car2home/v1/pair, the
       PairingManager calls `hass.config_entries.flow.async_configure`
       on this flow behind the scenes — equivalent to programmatically
       clicking Submit. The flow detects the resolved future and advances
       to `finish`, which creates the ConfigEntry.

If the user clicks Submit manually before the app confirms, the form is
re-shown (still waiting). If the code expires, the flow aborts with a
clean reason instead of the generic "Unknown error".
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from . import _ensure_global_setup
from .api import PairingManager
from .const import (
    CONF_CLIENT_ID,
    CONF_DEVICE_ID,
    CONF_DEVICE_SLUG,
    CONF_GARAGE_ID,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_NICKNAME,
    CONF_SW_VERSION,
    CONF_TARGETS,
    CONF_TOKEN,
    CONF_TOKENS,
    CONF_VIN,
    DOMAIN,
    MANUFACTURER_DEFAULT,
    PAIRING_CODE_TTL_SEC,
    TARGET_KIND_CAR,
    TARGET_KIND_GARAGE,
)
from .slug import build_unique_slug

_LOGGER = logging.getLogger(__name__)


class Car2HomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Pair-by-code config flow with auto-advance when the app confirms."""

    VERSION = 3

    def __init__(self) -> None:
        self._discovery: dict[str, Any] = {}
        self._code: str | None = None
        # Absolute expiration time of the code (HA-local timezone). Captured
        # when the code is generated so the "expires at HH:MM" hint in the
        # description is stable across re-renders and matches the actual TTL
        # enforced by the PairingManager.
        self._code_expires_at_label: str | None = None
        self._pair_waiter: asyncio.Task | None = None
        self._pair_result: dict[str, Any] | None = None
        self._pair_error: str | None = None

    # ─── Entry points ─────────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Entry point from the Add Integration UI."""
        _ensure_global_setup(self.hass)
        return await self.async_step_pair(user_input)

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> FlowResult:
        """Service discovered on the local network."""
        _ensure_global_setup(self.hass)
        properties = discovery_info.properties or {}
        device_id = properties.get("device_id") or discovery_info.name
        model = properties.get("model") or "Car 2 Home"
        manufacturer = properties.get("manufacturer") or "Car 2 Home"

        # Identity is the stable per-car device_id (the car GUID), NOT the VIN
        # (empty at pair time). Same car rediscovered → already configured.
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()

        self._discovery = {
            "host": str(discovery_info.host),
            "port": discovery_info.port,
            CONF_DEVICE_ID: device_id,
            CONF_VIN: properties.get("vin"),
            CONF_MODEL: model,
            CONF_MANUFACTURER: manufacturer,
            CONF_NICKNAME: properties.get("nickname"),
            CONF_SW_VERSION: properties.get("sw"),
        }
        self.context["title_placeholders"] = {"name": f"{model}"}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="zeroconf_confirm",
                description_placeholders={
                    "model": self._discovery.get(CONF_MODEL, ""),
                    "host": self._discovery.get("host", ""),
                },
            )
        return await self.async_step_pair()

    # ─── Pairing: show code, auto-advance on app POST ─────────────────────────

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the pairing code with full instructions (`async_show_form`).

        Trade-off: HA's ``async_show_progress`` auto-advances via WebSocket
        but only renders the progress-action string — it hides the step
        description, so the user cannot see the code there. ``async_show_form``
        renders the full markdown (title + code + instructions) but the
        frontend only updates on a click. So the UX is:
          1. User sees the code on this form.
          2. User types it in the app and confirms there.
          3. User comes back to HA and clicks Submit → flow finishes instantly
             because the background waiter has already resolved.
        """
        pairing: PairingManager = self.hass.data[DOMAIN]["_pairing"]

        # Generate the code exactly once per flow instance.
        if self._code is None:
            self._code = pairing.start(self.flow_id, self._discovery)
            # Compute the expiration label ONCE. Recomputing on every re-render
            # would make the displayed time creep back as the user interacts.
            expires = dt_util.now() + timedelta(seconds=PAIRING_CODE_TTL_SEC)
            self._code_expires_at_label = expires.strftime("%H:%M")

        # Launch the background waiter exactly once.
        if self._pair_waiter is None:
            self._pair_waiter = self.hass.async_create_task(
                self._wait_for_pair(pairing, self._code)
            )

        # User clicked Submit.
        if user_input is not None:
            if self._pair_waiter.done():
                if self._pair_error:
                    return self.async_abort(reason=self._pair_error)
                return await self.async_step_finish()
            # Still waiting → re-render the same form so the user can try again.

        # Prefer the user's configured external URL so the example URL in the
        # form matches what actually works from the phone's network. Fall back
        # to internal_url (LAN) and finally to the generic homeassistant.local
        # placeholder if neither is configured.
        try:
            ha_url = get_url(
                self.hass, prefer_external=True, allow_external=True, allow_internal=True
            )
        except NoURLAvailableError:
            ha_url = "https://homeassistant.local:8123"

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            description_placeholders={
                "code": " ".join(list(self._code)),
                "ttl_minutes": str(PAIRING_CODE_TTL_SEC // 60),
                "expires_at": self._code_expires_at_label or "",
                "ha_url": ha_url,
            },
        )

    async def _wait_for_pair(
        self, pairing: PairingManager, code: str
    ) -> None:
        """Resolve when the app POSTs the code (or on timeout)."""
        try:
            self._pair_result = await asyncio.wait_for(
                pairing.wait_for(code, timeout=PAIRING_CODE_TTL_SEC),
                timeout=PAIRING_CODE_TTL_SEC,
            )
        except asyncio.TimeoutError:
            self._pair_error = "timeout"
        except ValueError as err:
            self._pair_error = str(err)
        except Exception:  # pragma: no cover - defensive
            _LOGGER.exception("Unexpected pairing error")
            self._pair_error = "unknown"

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finalize: create the garage ConfigEntry or link a phone/car to it."""
        if self._pair_error or not self._pair_result:
            return self.async_abort(reason=self._pair_error or "unknown")

        result = self._pair_result
        manufacturer = (
            result.get(CONF_MANUFACTURER) or self._discovery.get(CONF_MANUFACTURER)
        )
        model = result.get(CONF_MODEL) or self._discovery.get(CONF_MODEL)
        nickname = result.get(CONF_NICKNAME) or self._discovery.get(CONF_NICKNAME)
        device_id = result.get(CONF_DEVICE_ID) or self._discovery.get(CONF_DEVICE_ID)

        # Garage identity is the config-entry unique_id: acct_{sub} (signed in)
        # or dev_{clientId}. Two phones of one account compute the same value and
        # share one garage. Fall back to the car GUID / client id if an older app
        # doesn't send it (that phone just gets its own single-car garage).
        garage_id = (
            result.get(CONF_GARAGE_ID)
            or device_id
            or result.get(CONF_CLIENT_ID)
            or "car2home"
        )
        await self.async_set_unique_id(garage_id, raise_on_progress=False)

        title = f"{model} · {nickname}" if nickname else (model or "Car 2 Home")

        # Same garage already configured (a second phone of the same account, or a
        # re-pair of the same phone) → link into it instead of creating a duplicate.
        existing = next(
            (e for e in self._async_current_entries() if e.unique_id == garage_id),
            None,
        )
        if existing is not None:
            self._link_to_garage(existing, result, device_id, manufacturer, model, nickname)
            return self.async_abort(reason="device_linked")

        # Fresh garage: seed the target catalogue with the stable garage-hub
        # device plus the paired car. Remaining cars arrive in the first hello.
        car_slug = build_unique_slug(manufacturer, model, nickname, set())
        targets = {
            garage_id: {
                "kind": TARGET_KIND_GARAGE,
                "id": garage_id,
                "device_slug": "car2home",
                "model": "Garage",
                "manufacturer": MANUFACTURER_DEFAULT,
                "name": "Car 2 Home",
                "nickname": None,
                "vin": None,
            },
        }
        # Guard: if an older app omitted garage_id, garage_id falls back to
        # device_id — don't let the car target overwrite the garage target under
        # the same key (that would attach ws_connected/switch to the car device).
        if device_id and device_id != garage_id:
            targets[device_id] = self._car_target(
                device_id, car_slug, manufacturer, model, nickname, result.get(CONF_VIN)
            )

        client_id = result.get(CONF_CLIENT_ID) or "default"
        return self.async_create_entry(
            title=title,
            data={
                **self._discovery,
                **result,
                CONF_GARAGE_ID: garage_id,
                CONF_DEVICE_SLUG: car_slug,
                CONF_TARGETS: targets,
                CONF_TOKENS: {client_id: result[CONF_TOKEN]},
            },
        )

    @staticmethod
    def _car_target(
        car_id: str,
        slug: str,
        manufacturer: str | None,
        model: str | None,
        nickname: str | None,
        vin: str | None,
    ) -> dict[str, Any]:
        return {
            "kind": TARGET_KIND_CAR,
            "id": car_id,
            "device_slug": slug,
            "model": model or "Vehicle",
            "manufacturer": manufacturer or MANUFACTURER_DEFAULT,
            "nickname": nickname or None,
            "vin": (vin or "").strip() or None,
            "is_primary": True,
        }

    def _link_to_garage(
        self,
        entry: config_entries.ConfigEntry,
        result: dict[str, Any],
        device_id: str | None,
        manufacturer: str | None,
        model: str | None,
        nickname: str | None,
    ) -> None:
        """Link a phone (and its active car) to an existing garage entry.

        Adds this phone's token to the map and seeds the car target if it isn't
        already known. No reload: token matching reads entry.data live, so an
        already-connected phone is not disconnected. The full car catalogue is
        rebuilt from the next hello regardless.
        """
        tokens = dict(entry.data.get(CONF_TOKENS) or {})
        legacy = entry.data.get(CONF_TOKEN)
        if not tokens and legacy:
            tokens["default"] = legacy
        client_id = result.get(CONF_CLIENT_ID) or "default"
        tokens[client_id] = result[CONF_TOKEN]

        new_data = {**entry.data, CONF_TOKENS: tokens}

        targets = dict(entry.data.get(CONF_TARGETS) or {})
        if device_id and device_id not in targets:
            existing_slugs = {
                t.get("device_slug") for t in targets.values() if t.get("device_slug")
            }
            slug = build_unique_slug(manufacturer, model, nickname, existing_slugs)
            targets[device_id] = self._car_target(
                device_id, slug, manufacturer, model, nickname, result.get(CONF_VIN)
            )
            new_data[CONF_TARGETS] = targets

        self.hass.config_entries.async_update_entry(entry, data=new_data)
