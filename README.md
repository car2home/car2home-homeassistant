<p align="center">
  <img src="https://raw.githubusercontent.com/car2home/car2home-homeassistant/refs/heads/main/custom_components/car2home/brand/icon.png" alt="Car 2 Home" width="192" />
</p>

# Car 2 Home for Home Assistant

[![HACS Custom][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub All Releases][downloads_shield]][releases]
[![GitHub Discussions][discussions_shield]][discussions]
[![HACS Validation][hacs_validate_shield]][actions]
[![Validate with hassfest][hassfest_shield]][actions]
[![License: Apache 2.0][license_shield]][license]

A native Home Assistant custom integration that streams live OBD-II telemetry from the **Car 2 Home** mobile app (Android / iOS) straight into Home Assistant, with no MQTT broker, no Torque-style polling and no intermediate cloud.

## Overview

This integration turns your phone running the **Car 2 Home** app into a native Home Assistant data source. The app reads your car's OBD-II port (via a Bluetooth or Wi-Fi ELM327 adapter), augments the stream with GPS, trip analytics and TPMS data, and sends everything to Home Assistant over a single persistent WebSocket. Each vehicle shows up as its own HA Device with properly classified sensors ready to drop into dashboards, energy panels and automations.

Unlike HTTP-polling integrations (Torque-style) or broker-based setups (MQTT), the link is **bidirectional and always warm**: the app pushes updates the moment they arrive from the ECU, and Home Assistant can request on-demand actions (DTC scan, re-announce, identify) back to the phone via the same socket.

## Features

- 🚗 **Real-time vehicle telemetry**: live RPM, speed, fuel, temperatures, TPMS, battery voltage and more, streamed at 1 to 4 Hz.
- 🔌 **Native HA integration**, with no MQTT broker, no extra infrastructure and no cloud relay.
- 🔐 **6-digit pairing**: the Config Flow generates a one-shot code you type in the app (Apple TV style). The app receives an integration-scoped token, *not* a full HA long-lived access token.
- 🧭 **Zeroconf discovery**: the app advertises `_car2home._tcp.local.` so HA offers a pre-filled Config Flow when the phone is on the same LAN *(enabled in a future app release; manual pairing works today)*.
- 🛰️ **Local push over WebSocket**: persistent connection with configurable heartbeats (default 20 s), automatic reconnect with exponential backoff and circuit breaker, delta-only state updates.
- 📡 **Automatic HTTP fallback**: if the WebSocket keeps flapping the app degrades to a POST-per-frame ingest endpoint, then auto-restores the WebSocket when it comes back.
- 📶 **Wi-Fi only sync mode** (optional): the app buffers telemetry locally during the trip and drains the backlog as soon as it joins any Wi-Fi. Two opt-ins let you decide what still flows over mobile data:
  - **Send events online** keeps the integration "alive" in HA with service status and semantic events.
  - **Send location online** trickles the vehicle position out once per minute so home/work automations still work.
- 🔁 **Bidirectional Online / Wi-Fi only switch**: a `switch.*_sync_mode_online` entity lets you flip the app's mode straight from HA; the app echoes the new value back so the switch stays in sync.
- 🗺️ **Vehicle device tracker**: the car's location as a native HA `device_tracker`, from two sources and nothing else. While a trip is recording it follows live GPS; the rest of the time it holds the car's parking spot, carrying `address` and `parked_at` as attributes, with `source` telling you which of the two you are looking at. It does not follow the phone around when you are not driving.
- 📊 **Rich device classes**: speed, temperature, pressure, voltage, volume, volume flow rate, distance, duration, energy, power, battery and more, so HA renders the correct units, charts and statistics automatically.
- 📈 **Long-term statistics ready**: distance, duration and energy sensors carry `state_class=total_increasing` out of the box.
- 🚙 **Multi-vehicle native**: each car becomes its own `ConfigEntry` and HA Device, fully isolated.
- 🏷️ **Human-readable Entity IDs**: `sensor.car2home_toyota_corolla_cross_rpm` instead of opaque hashes (see [Entity naming convention](#entity-naming-convention)).
- 🔁 **Survives restarts and outages**: data sensors use `RestoreSensor` and never flip to `unavailable`. Transport health is surfaced in a dedicated diagnostic `binary_sensor.*_connection`.
- 🌐 **Works anywhere HA is reachable**: LAN, Nabu Casa Cloud, Cloudflare Tunnel, Tailscale, WireGuard, or any reverse proxy that forwards WebSockets.
- 🧰 **Extensible actions**: HA services to request DTC scans, force a descriptor re-announce, or ping the app.
- 🌍 **Multilingual Config Flow**: English, Brazilian and European Portuguese, German, Spanish, French and Italian out of the box, with more languages inheriting from the mobile app.

## Quick Start

### Installation

#### Option 1: HACS (recommended)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

1. Open **HACS** in Home Assistant.
2. Go to **Integrations**, then the **⋮** menu, then **Custom repositories**.
3. Add `https://github.com/car2home/car2home-homeassistant` as category **Integration**.
4. Install **Car 2 Home**.
5. Restart Home Assistant.
6. Go to **Settings** → **Devices & Services** → **Add Integration**.
7. Search for **Car 2 Home** and follow the pairing flow.

#### Option 2: Manual installation

1. Copy `custom_components/car2home/` to your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration from **Settings** → **Devices & Services**.

### Pairing

No Long-Lived Access Token, no manual config files. The whole flow is a 6-digit code shown on one side and typed on the other. End-to-end it takes under a minute.

**On Home Assistant**

1. Go to **Settings → Devices & Services → + Add Integration**.
2. Search for and select **Car 2 Home**.
3. A single screen opens with a large **6-digit pairing code** at the top and a numbered instruction list below it. **Keep this screen open** and do not click Submit yet.

**On the mobile app**

4. Open the **Car 2 Home** app and navigate to **Settings → Home Assistant → Integration**.
5. In the **URL** field, type the URL of the Home Assistant instance you opened in step 1. For example `https://homeassistant.local:8123` (local), or your public Nabu Casa / Cloudflare Tunnel / Tailscale / reverse-proxy URL.
6. If your HA uses a self-signed certificate, toggle **Accept untrusted certificate** on. (When the URL is a private or `.local` address the app enables this automatically.)
7. Tap **Pair**. Type the 6-digit code from step 3 into the numeric field that appears and tap **Confirm**.
8. The app shows a **"Paired successfully"** confirmation.

**Back on Home Assistant**

9. Click **Submit** on the pairing screen. The flow finishes immediately, because the backend has already validated the code in step 7. Submit is just the UI trigger that tells the frontend "go to success".
10. The vehicle appears in **Devices & Services** as a new Car 2 Home device, with every sensor the app is publishing ready to be dropped on dashboards.

Why the Submit click at the end: Home Assistant has two APIs for config flow screens. `async_show_progress` can auto-advance without a click but only renders a spinner and hides the description markdown where the code lives. `async_show_form` renders the full instructions and the code but only updates on a click. This integration prioritises having a visible code and clear instructions, so it uses `async_show_form` and asks for one click at the end. Official integrations like **Plex**, **Nabu Casa**, **Google Nest** and **Sonos** follow the same pattern for the same reason.

**What happens under the hood**

- The 6-digit code is generated by the plugin when you open the config flow and is **the** one-shot authentication for `POST /api/car2home/v1/pair`. No other auth is required.
- The app receives `{ws_url, token}` back from that POST and stores the token in platform-native secure storage (Keychain on iOS, Keystore on Android).
- After pairing, the app opens the persistent WebSocket to `ws_url`, sends a `hello` frame with the full sensor descriptor, and starts streaming live state.

**Troubleshooting**

- **Code expired** (5 min window): close the HA flow and click Add Integration again. A new code is generated every flow.
- **"invalid_or_expired_code"**: the code you typed in the app doesn't match what HA is showing. Double-check for typos.
- **"timeout"**: the app didn't confirm within 5 minutes. Retry.
- **"Unknown error"**: no longer possible. Any failure now aborts with one of the specific reasons above.

**Re-pairing / disconnecting**

In the app, open **Settings → Home Assistant → Integration**. If already paired, the tab shows the instance URL and a red **Disconnect** button. Tapping it wipes the stored token and URL. To pair the same vehicle again, just repeat the flow from step 1. The existing Config Entry in HA is detected by VIN and reused, so no duplicate device is created.

## Entity naming convention

Every entity's `unique_id`, and therefore its HA Entity ID, follows a human-readable, stable slug built from manufacturer and model:

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

The VIN, when the ECU reports it, is kept as a secondary Device Registry identifier so re-pairing the same car doesn't create duplicates. It never appears in entity names.

## Supported sensors

The integration creates entities **dynamically** from the descriptor the app sends in its first `hello` frame. What you see depends on which PIDs your vehicle actually exposes and which ones are enabled in the app. Typical categories:

- **Engine**: RPM, coolant temperature, intake air temperature, manifold pressure, throttle position, engine load, timing advance, MAF.
- **Fuel**: fuel level, fuel rate, fuel type, trip fuel used, trip fuel economy, ethanol percentage, **trip cost** (computed from the fuel price you set in the app).
- **Powertrain**: vehicle speed, GPS speed, average trip speed, trip distance, odometer, gear, runtime.
- **Electrical**: battery voltage, control module voltage, O2 sensor voltages.
- **Emissions / diagnostics**: MIL, DTC count, catalyst temperatures, EGR, evap pressure.
- **Comfort / environment**: ambient temperature, barometric pressure.
- **Hybrid / EV**: HVESS voltage, current, charge/discharge energy, state of health, battery pack temperature.
- **TPMS**: per-wheel pressure, temperature, sensor ID and low-pressure binary sensor.
- **GPS**: the vehicle's position as a native `device_tracker` — live while a trip records, the parking spot otherwise. Latitude, longitude, altitude, accuracy and speed are also available as individual sensors (off by default); they follow the same rule, so none of them report the phone outside a trip.
- **Diagnostics**: ELM327 version, OBD protocol, adapter voltage, ECU latency, WebSocket RTT, reconnect counters, current sync mode.

All units are metric on the wire; Home Assistant converts the display to your configured unit system.

## Events

Beyond the live sensor stream, the integration fires semantic events on the Home Assistant event bus when meaningful things happen *to the vehicle*. Every event arrives as `car2home_{event}` and carries `vin`, `device_slug` and `timestamp_ms` alongside the event-specific payload.

| Event | Fired when | Highlights |
|---|---|---|
| `car2home_trip_started` | A new trip begins | `trip_id`, `data_source` (`obd` or `gps`), `start_time`, `start_location` (geocoded). |
| `car2home_trip_ended` | A trip is finalized and saved | distance, duration, avg/max speed and RPM, fuel, average consumption, CO₂, full `driving_metrics` block (hard acceleration/braking/cornering counts, speeding, idle time and idle fuel, fuel cut, high-RPM and high-speed time, night driving, phone usage), `safe_score`, `eco_score`, `end_location`. |
| `car2home_parking_detected` | Right after the trip ends, at the last known GPS point | `parking_id`, `trip_id`, geocoded `location`, trip duration and distance. |
| `car2home_dtc_found` | A DTC scan is completed and persisted | scan mode, counts, and full confirmed / pending / permanent lists with descriptions, symptoms, cause and solution. |
| `car2home_harsh_event` | A hard brake, hard acceleration or sharp cornering is detected (3 s debounce) | `type`, `magnitude_g`, `speed_kmh`, `location`, `trip_id`. |
| `car2home_ecu_online` / `car2home_ecu_offline` | ECU connectivity flips | `device_name`, `elm_version`, `obd_protocol`, `latency_ms`, `reason`. |

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
            Duration: {{ (trigger.event.data.duration_seconds / 60) | round(0) }} min,
            Safe score: {{ trigger.event.data.safe_score }},
            Eco score: {{ trigger.event.data.eco_score or 'n/a' }}
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

- **Nabu Casa Home Assistant Cloud**: zero configuration.
- **Cloudflare Tunnel (`cloudflared`)**: enable WebSockets in the Zero Trust dashboard. The default 20-second app ping stays well under Cloudflare's 100-second idle timeout. If you raise the ping interval in the app settings, keep it below 90 s for Cloudflare.
- **Tailscale / Tailscale Funnel**: mesh or public Funnel, nothing special to configure.
- **WireGuard**: point the app at the HA internal IP. Transparent VPN.
- **nginx / Traefik / Caddy**: standard WebSocket upgrade headers required:

  ```nginx
  location / {
      proxy_pass http://homeassistant:8123;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_read_timeout 3600s;
  }
  ```

## Publishing & distribution

This integration is currently distributed as a **HACS custom repository**. There are three optional next steps if you want broader reach:

1. **HACS default**: submit a PR to [`hacs/default`](https://github.com/hacs/default) listing this repo. After merge, the integration shows up in the HACS Integrations catalog without the user adding a custom repo.
2. **Brand icons** on `brands.home-assistant.io`: fork [`home-assistant/brands`](https://github.com/home-assistant/brands), copy the four PNGs from this repo's [`brands/`](brands/) folder into `custom_integrations/car2home/`, and open a PR. After merge the integration icon shows up automatically in **Settings → Devices & Services** on every HA instance worldwide (a 24 h CDN cache). Detailed step-by-step in [`brands/README.md`](brands/README.md).
3. **Official integration** in HA core: a much bigger undertaking. Requires moving the code into `homeassistant/components/car2home/`, adding HA test coverage, passing the architecture review and being adopted by a code owner inside the project. Not required for normal use, but the goal long term once the API stabilises.

## Requirements

- Home Assistant **2024.12** or later.
- **Car 2 Home** mobile app, paired to your vehicle via an ELM327 Bluetooth or Wi-Fi adapter.
- Any OBD-II compliant vehicle (most cars built from 1996 onwards in the US, 2001+ in the EU).

## Example use cases

- Automate your garage door when the car comes home.
- Track long-term fuel economy and trip cost in the Energy dashboard.
- Alert on low TPMS pressure or high coolant temperature.
- Record per-trip distance, duration and driving-score statistics.
- Surface DTC warnings with push notifications.
- Log vehicle voltage drops that indicate a failing battery.
- Trigger Wi-Fi-only batch sync to drain the daily backlog without burning mobile data.

## Contributing

Issues and pull requests are welcome. Please open an issue first if you're planning a larger change so we can align on approach.

## License

Apache License 2.0, see [LICENSE](LICENSE).

## Credits

Built to complement the **Car 2 Home** mobile app. Inspired in part by the architecture of other community OBD integrations (notably the Torque HTTP bridge), but designed from the ground up around a push-based, delta-efficient WebSocket protocol with full Home Assistant device-class coverage.

<!-- Badge reference links -->
[hacs_shield]: https://img.shields.io/badge/HACS-Custom-orange?style=popout&logo=HomeAssistantCommunityStore&logoColor=white
[hacs]: https://hacs.xyz/docs/faq/custom_repositories
[latest_release]: https://github.com/car2home/car2home-homeassistant/releases/latest
[releases_shield]: https://img.shields.io/github/release/car2home/car2home-homeassistant.svg?style=popout
[releases]: https://github.com/car2home/car2home-homeassistant/releases
[downloads_shield]: https://img.shields.io/github/downloads/car2home/car2home-homeassistant/total?style=popout
[discussions]: https://github.com/car2home/car2home-homeassistant/discussions
[discussions_shield]: https://img.shields.io/github/discussions/car2home/car2home-homeassistant?style=popout&logo=github
[actions]: https://github.com/car2home/car2home-homeassistant/actions
[hacs_validate_shield]: https://github.com/car2home/car2home-homeassistant/actions/workflows/hacs.yml/badge.svg
[hassfest_shield]: https://github.com/car2home/car2home-homeassistant/actions/workflows/hassfest.yml/badge.svg
[license_shield]: https://img.shields.io/badge/License-Apache_2.0-blue.svg
[license]: LICENSE
