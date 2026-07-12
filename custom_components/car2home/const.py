"""Constants for the Car 2 Home integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "car2home"
MANUFACTURER_DEFAULT = "Car 2 Home"

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.SWITCH,
]

WIRE_PROTOCOL_VERSION = 2
WS_PATH = "/api/car2home/v1/ws"
HTTP_INGEST_PATH = "/api/car2home/v1/ingest"
PAIR_PATH = "/api/car2home/v1/pair"

PAIRING_CODE_TTL_SEC = 300
PAIRING_CODE_DIGITS = 6

PING_INTERVAL_SEC = 20
STALE_THRESHOLD_SEC = 120

CONF_VIN = "vin"
CONF_DEVICE_ID = "device_id"  # stable per-car GUID (CarProfile.Id), unique at pair time
CONF_DEVICE_SLUG = "device_slug"  # car2home_{manufacturer}_{model}[_{nickname}][_{N}], readable HA name
CONF_TOKEN = "token"  # legacy single token; superseded by CONF_TOKENS (kept for back-compat)
CONF_TOKENS = "tokens"  # {client_id: token} — one per paired phone
CONF_CLIENT_ID = "client_id"  # per-phone install id keying the token map

# Multi-car ("garage") model. One config entry = one garage; each car and the
# phone-level "garage hub" are separate HA devices keyed by an immutable target
# id (car GUID, or the garage id for the hub). See coordinator.py / entity.py.
CONF_GARAGE_ID = "garage_id"  # config-entry unique_id: acct_{sub} (signed in) or dev_{clientId}
CONF_TARGETS = "targets"  # {target_id: {kind, id, device_slug, model, manufacturer, nickname, vin, is_primary}}
TARGET_KIND_GARAGE = "garage"  # the stable phone/connection-meta device
TARGET_KIND_CAR = "car"
CONF_NICKNAME = "nickname"  # user-set car nickname, folded into the device name / slug
CONF_LOCAL_URL = "local_url"
CONF_REMOTE_URL = "remote_url"
CONF_HOME_SSID = "home_ssid"
CONF_MANUFACTURER = "manufacturer"
CONF_MODEL = "model"
CONF_SW_VERSION = "sw_version"
CONF_HW_VERSION = "hw_version"

DEVICE_SLUG_PREFIX = "car2home"

SIGNAL_NEW_DESCRIPTOR = f"{DOMAIN}_new_descriptor"
SIGNAL_STATE_UPDATE = f"{DOMAIN}_state_update"
SIGNAL_AVAILABILITY = f"{DOMAIN}_availability"
SIGNAL_LOCATION = f"{DOMAIN}_location"

# Frame types
FRAME_HELLO = "hello"
FRAME_STATE = "state"
FRAME_LOCATION = "location"
FRAME_EVENT = "event"
FRAME_BACKFILL = "backfill"
FRAME_AVAILABILITY = "availability"
FRAME_PING = "ping"
FRAME_PONG = "pong"
FRAME_COMMAND = "command"
FRAME_ACK = "ack"
FRAME_ERROR = "error"
