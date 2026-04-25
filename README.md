<p align="center">
  <img src="icon.png" alt="Car 2 Home" width="128" height="128" />
</p>

# Car 2 Home — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A native Home Assistant custom integration that streams live OBD-II telemetry from the **Car 2 Home** mobile app (Android / iOS) straight into Home Assistant — no MQTT broker, no Torque-style polling, no intermediate cloud.

## Overview

This integration turns your phone running the **Car 2 Home** app into a native Home Assistant data source. The app reads your car's OBD-II port (via a Bluetooth or Wi-Fi ELM327 adapter), augments the stream with GPS, trip analytics and TPMS data, and sends everything to Home Assistant over a single persistent WebSocket. Each vehicle shows up as its own HA Device with properly classified sensors ready to drop into dashboards, energy panels, and automations.

Unlike HTTP-polling integrations (Torque-style) or broker-based setups (MQTT), the link is **bidirectional and always warm**: the app pushes updates the moment they arrive from the ECU, and Home Assistant can request on-demand actions (DTC scan, re-announce, identify) back to the phone via the same socket.

## Features

- 🚗 **Real-time vehicle telemetry** — live RPM, speed, fuel, temperatures, TPMS, battery voltage and more, streamed at 1–4 Hz
- 🔌 **Native HA integration** — no MQTT broker needed, no extra infrastructure, no cloud relay
- 🔐 **6-digit pairing** — Config Flow generates a one-shot code you type in the app (Apple TV-style). The app receives an integration-scoped token, *not* a full HA long-lived access token
- 🧭 **Zeroconf discovery** — the app advertises `_car2home._tcp.local.` so HA offers a pre-filled Config Flow when the phone is on the same LAN *(enabled in a future app release; manual pairing works today)*
- 🛰️ **Local push over WebSocket** — persistent connection with 20-second heartbeats, automatic reconnect, delta-only state updates
- 🗺️ **GPS device tracker** — phone location, accuracy, speed and bearing exposed as a native HA `device_tracker`
- 📊 **Rich device classes** — speed, temperature, pressure, voltage, volume, volume flow rate, distance, duration, energy, power, battery — so HA renders the correct units, charts and statistics automatically
- 📈 **Long-term statistics ready** — distance, duration and energy sensors carry `state_class=total_increasing` out of the box
- 🚙 **Multi-vehicle native** — each car becomes its own `ConfigEntry` and HA Device, fully isolated
- 🏷️ **Human-readable Entity IDs** — `sensor.car2home_toyota_corolla_cross_rpm` instead of opaque hashes (see [Entity naming convention](#entity-naming-convention))
- 🔁 **Survives restarts and outages** — sensors use `RestoreSensor` and never flip to `unavailable`; transport health is surfaced in a dedicated diagnostic `binary_sensor.*_connection`
- 🌐 **Works anywhere HA is reachable** — LAN, Nabu Casa Cloud, Cloudflare Tunnel, Tailscale, WireGuard, or any reverse proxy that forwards WebSockets
- 🧰 **Extensible actions** — HA services to request DTC scans, force a descriptor re-announce, or ping the app
- 🌍 **Multilingual Config Flow** — English and Brazilian Portuguese, with more languages inheriting from the mobile app

## Quick Start

### Installation

#### Option 1: HACS (recommended)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

1. Open **HACS** in Home Assistant
2. Go to **Integrations** → **⋮** menu → **Custom repositories**
3. Add `https://github.com/fabianosan/car2home-homeassistant` as category **Integration**
4. Install **Car 2 Home**
5. Restart Home Assistant
6. Go to **Settings** → **Devices & Services** → **Add Integration**
7. Search for **Car 2 Home** and follow the pairing flow

#### Option 2: Manual installation

1. Copy `custom_components/car2home/` to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration from **Settings** → **Devices & Services**

### Pairing

No Long-Lived Access Token, no manual config files. The whole flow is a 6-digit code shown on one side and typed on the other. End-to-end it takes under a minute.

**On Home Assistant**

1. Go to **Settings → Devices & Services → + Add Integration**.
2. Search for and select **Car 2 Home**.
3. A single screen opens showing a large **6-digit pairing code** at the top and a numbered instruction list below it. **Keep this screen open** — do not click Submit yet.

**On the mobile app**

4. Open the **Car 2 Home** app and navigate to **Settings → Home Assistant → Integration**.
5. In the **URL** field, type the URL of the Home Assistant instance you opened in step 1 — for example `https://homeassistant.local:8123` (local) or your public Nabu Casa / Cloudflare Tunnel / Tailscale / reverse-proxy URL.
6. If your HA uses a self-signed certificate, toggle **Accept untrusted certificate** on. (When the URL is a private/.local address the app enables this automatically.)
7. Tap **Pair**. Type the 6-digit code from step 3 into the numeric field that appears and tap **Confirm**.
8. The app shows a **"Paired successfully"** confirmation.

**Back on Home Assistant**

9. Click **Submit** on the pairing screen. The flow finishes immediately — the backend has already validated the code in step 7, so Submit is just the UI trigger that tells the frontend "go to success".
10. The vehicle appears in **Devices & Services** as a new Car 2 Home device, with every sensor the app is publishing ready to be dropped on dashboards.

Why the Submit click at the end: Home Assistant has two APIs for config flow screens. `async_show_progress` can auto-advance without a click but only renders a spinner — it hides the description markdown where the code lives. `async_show_form` renders the full instructions and the code but only updates on a click. This integration prioritises having a visible code + clear instructions, so it uses `async_show_form` and asks for one click at the end. Official integrations like **Plex**, **Nabu Casa**, **Google Nest** and **Sonos** follow the same pattern for the same reason.

**What happens under the hood**

- The 6-digit code is generated by the plugin when you open the config flow and is **the** one-shot authentication for `POST /api/car2home/v1/pair`. No other auth is required.
- The app receives `{ws_url, token}` back from that POST and stores the token in platform-native secure storage (Keychain on iOS, Keystore on Android).
- After pairing, the app opens the persistent WebSocket to `ws_url`, sends a `hello` frame with the full sensor descriptor, and starts streaming live state.

**Troubleshooting**

- **Code expired** (5 min window): close the HA flow and click Add Integration again — a new code is generated every flow.
- **"invalid_or_expired_code"**: the code you typed in the app doesn't match what HA is showing. Double-check for typos.
- **"timeout"**: the app didn't confirm within 5 minutes. Retry.
- **"Unknown error"**: no longer possible — any failure now aborts with one of the specific reasons above.

**Re-pairing / disconnecting**

In the app, open **Settings → Home Assistant → Integration** tab. If already paired, the tab shows the instance URL and a red **Disconnect** button. Tapping it wipes the stored token and URL. To pair the same vehicle again, just repeat the flow from step 1; the existing Config Entry in HA is detected by VIN and reused (no duplicate device).

## Entity naming convention

Every entity's `unique_id` — and therefore its HA Entity ID — follows a human-readable, stable slug built from manufacturer and model:

```
car2home_{manufacturer}_{model}[_{N}]_{sensor_id}
```

Real examples:

| Scenario | Entity ID |
|---|---|
| One Toyota Corolla Cross | `sensor.car2home_toyota_corolla_cross_rpm` |
| Same vehicle, speed PID | `sensor.car2home_toyota_corolla_cross_speed` |
| A second identical Corolla Cross | `sensor.car2home_toyota_corolla_cross_2_rpm` |
| Ford F-150 | `sensor.car2home_ford_f_150_engine_coolant_temp` |

The VIN, when the ECU reports it, is kept as a secondary Device Registry identifier so re-pairing the same car doesn't create duplicates — but it never appears in entity names.

## Supported sensors

The integration creates entities **dynamically** from the descriptor the app sends in its first `hello` frame. What you see depends on what PIDs your vehicle actually exposes and which ones are enabled in the app. Typical categories:

- **Engine**: RPM, coolant temperature, intake air temperature, manifold pressure, throttle position, engine load, timing advance, MAF
- **Fuel**: Fuel level, fuel rate, fuel type, trip fuel used, trip fuel economy, ethanol %
- **Powertrain**: Vehicle speed, GPS speed, average trip speed, trip distance, odometer, gear, runtime
- **Electrical**: Battery voltage, control module voltage, O2 sensor voltages
- **Emissions / diagnostics**: MIL, DTC count, catalyst temperatures, EGR, evap pressure
- **Comfort / environment**: Ambient temperature, barometric pressure
- **Hybrid / EV**: HVESS voltage, current, charge/discharge energy, state of health, battery pack temperature
- **TPMS**: Per-wheel pressure, temperature, sensor ID and low-pressure binary sensor
- **GPS**: Latitude, longitude, altitude, accuracy, bearing, battery level — exposed as a native `device_tracker`
- **Diagnostics**: ELM327 version, OBD protocol, adapter voltage, ECU latency, WebSocket RTT, reconnect counters

All units are metric on the wire; Home Assistant converts the display to your configured unit system.

## Events

Beyond the live sensor stream, the integration fires semantic events on the Home Assistant event bus when meaningful things happen *to the vehicle*. Every event arrives as `car2home_{event}` and carries `vin`, `device_slug` and `timestamp_ms` alongside the event-specific payload.

| Event | Fired when | Highlights |
|---|---|---|
| `car2home_trip_started` | A new trip begins | `trip_id`, `start_time`, `start_location` (geocoded) |
| `car2home_trip_ended` | A trip is finalized and saved | distance, duration, avg/max speed, fuel, CO₂, hard acceleration/braking/cornering counts, speeding, idle, night driving, `safe_score`, `eco_score`, `end_location` |
| `car2home_parking_detected` | Right after the trip ends, at the last known GPS point | `parking_id`, `trip_id`, geocoded `location`, trip duration and distance |
| `car2home_dtc_found` | A DTC scan is completed and persisted | scan mode, counts, and full confirmed / pending / permanent lists with descriptions, symptoms, cause, solution |
| `car2home_harsh_event` | A hard brake / hard acceleration / sharp cornering is detected (3 s debounce) | `type`, `magnitude_g`, `speed_kmh`, `location`, `trip_id` |
| `car2home_ecu_online` / `car2home_ecu_offline` | ECU connectivity flips | `device_name`, `elm_version`, `obd_protocol`, `latency_ms`, `reason` |

### Example automations

End-of-trip summary as a persistent notification:

```yaml
automation:
  - alias: "Trip summary"
    trigger:
      - platform: event
        event_type: car2home_trip_ended
    action:
      - service: persistent_notification.create
        data:
          title: "Trip of {{ trigger.event.data.distance_km }} km"
          message: >-
            Duration: {{ (trigger.event.data.duration_seconds / 60) | round(0) }} min ·
            Safe score: {{ trigger.event.data.safe_score }} ·
            Eco score: {{ trigger.event.data.eco_score or '—' }}
```

DTC alert on WhatsApp when the check-engine light trips a new scan:

```yaml
automation:
  - alias: "New DTC"
    trigger:
      - platform: event
        event_type: car2home_dtc_found
    condition:
      - "{{ trigger.event.data.confirmed_count > 0 }}"
    action:
      - service: notify.mobile_app_phone
        data:
          title: "New DTC on {{ trigger.event.data.device_slug }}"
          message: >-
            {% for c in trigger.event.data.confirmed_codes -%}
            {{ c.code }}: {{ c.description }}{{ '\n' }}
            {%- endfor %}
```

Welcome-home when the car parks at a known address:

```yaml
automation:
  - alias: "Welcome home"
    trigger:
      - platform: event
        event_type: car2home_parking_detected
    condition:
      - "{{ 'Rua de Casa' in (trigger.event.data.location.address or '') }}"
    action:
      - service: light.turn_on
        target: { entity_id: light.garagem }
      - service: lock.unlock
        target: { entity_id: lock.porta_frente }
```

## Reverse proxy / tunnel compatibility

The WebSocket endpoint is a standard `HomeAssistantView`, so any transport that proxies WS traffic works without plugin-side changes:

- **Nabu Casa Home Assistant Cloud** — zero configuration
- **Cloudflare Tunnel (`cloudflared`)** — enable WebSockets in the Zero Trust dashboard; the 20-second app ping stays well under Cloudflare's 100-second idle timeout
- **Tailscale / Tailscale Funnel** — mesh or public Funnel, nothing special to configure
- **WireGuard** — point the app at the HA internal IP; transparent VPN
- **nginx / Traefik / Caddy** — standard WebSocket upgrade headers required:

  ```nginx
  location / {
      proxy_pass http://homeassistant:8123;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_read_timeout 3600s;
  }
  ```

## Requirements

- Home Assistant **2024.12** or later
- **Car 2 Home** mobile app, paired to your vehicle via an ELM327 Bluetooth or Wi-Fi adapter
- Any OBD-II compliant vehicle (most cars built from 1996 onwards in the US, 2001+ in the EU)

## Example use cases

- Automate your garage door when the car comes home
- Track long-term fuel economy in the Energy dashboard
- Alert on low TPMS pressure or high coolant temperature
- Record per-trip distance and duration statistics
- Surface DTC warnings with push notifications
- Log vehicle voltage drops that indicate a failing battery

## Contributing

Issues and pull requests are welcome. Please open an issue first if you're planning a larger change so we can align on approach.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## Credits

Built to complement the **Car 2 Home** mobile app. Inspired in part by the architecture of other community OBD integrations — notably the Torque HTTP bridge — but designed from the ground up around a push-based, delta-efficient WebSocket protocol with full Home Assistant device-class coverage.
