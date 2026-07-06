<p align="center">
  <img src="custom_components/eveus/brand/icon.png" alt="Eveus Charger" width="120" />
</p>

<h1 align="center">⚡ Eveus Charger for Home Assistant</h1>

<p align="center">
  Local-polling Home Assistant integration for Eveus EV chargers — full entity set and native statistics, for both v1 and v2 hardware generations.
</p>

<p align="center">
  <a href="https://github.com/Soundistor/ha-eveus/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/Soundistor/ha-eveus?style=flat-square"></a>
  <a href="https://github.com/Soundistor/ha-eveus/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/Soundistor/ha-eveus/total?style=flat-square"></a>
  <img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue?style=flat-square">
  <a href="https://hacs.xyz"><img alt="HACS Custom" src="https://img.shields.io/badge/HACS-Custom-orange?style=flat-square"></a>
</p>

Originally based in part on [shlafik/eveuspro2ha](https://github.com/shlafik/eveuspro2ha), then rewritten around a single polling coordinator and HA-native quality requirements.

> [!TIP]
> Документація також доступна [**українською мовою 🇺🇦**](./readme.uk.md)

## About

[Eveus](https://eveus.ua/) (formerly the **Energy Star** trademark) is a Ukrainian manufacturer of portable EV chargers. This integration connects an Eveus charger to Home Assistant over the local network — no cloud and no account required.

Once configured, it lets you:

- monitor the charging **state**, current, voltage, power, energy and temperatures;
- **start / stop** charging and set the **charging current**;
- switch the charger's **AI / adaptive power mode**;
- track **per-session** and **daily** energy and charging time, ready for the Energy Dashboard.

The charger comes in two hardware generations — **v1** and **v2** — which expose different on-device HTTP APIs. You pick the matching model when adding the integration (see [Supported devices](#supported-devices)).

## What sets this integration apart

Several Home Assistant projects exist for Eveus chargers. This one focuses on:

- **Both hardware generations in one integration** — the v1 and v2 chargers expose different HTTP APIs; you pick the model in the config flow and the differences (state model, polarity, scaling, extra sensors) are handled internally.
- **First-class HA statistics** — correct `state_class` / `device_class` on energy, power, current and voltage, so long-term statistics and the Energy Dashboard work out of the box. Daily energy and charging-time sensors reset at local midnight and survive restarts.
- **HACS-grade plumbing** — diagnostics (with IP/credentials redacted), Repairs issues for real errors only, re-auth flow, and config-entry migration.
- **Single polling coordinator** — one source of truth for device state with dynamic polling (30 s while charging, 60 s otherwise) instead of per-entity requests.
- **Robust safety signals** — ground sensors use debounce to suppress transient glitches, while firmware fault states bypass debounce and trigger immediately.
- **Ukrainian-first localization** — UI strings in Ukrainian, English and Russian, with a bundled brand icon.

## Supported devices

| Model | Min current | JSON fields |
|-------|-------------|-------------|
| v1 | 7 A | 41 |
| v2 | 6 A | 97 |

<p align="center">
  <img src="images/eveus-v1-cable.jpg" alt="Eveus v1 portable charger" width="520" />
</p>

### v1 vs v2 differences

| Feature | v1 | v2 |
|---------|----|----|
| `evseEnabled` polarity | `1` = charging active | `0` = charging active |
| State model | 22 states — errors and limits encoded in single `state` field | 8 top-level states in `state` + `subState` for limit / error detail |
| AI modes | Off, Voltage | Off, Voltage, Tesla (auto), Power |
| `systemTime` format | `"HH:MM:SS"` string | Unix timestamp (integer) |
| Measurement values | Raw integers — `curMeas1` and energy fields scaled ×0.1 | Real floats in native units |
| `powerMeas` | Not in response — calculated from V × I | Reported directly by device |
| Extra sensors | — | `subState`, `vBat`, `RSSI`, `IEM1`, `IEM2` |
| Time sync | — | `sync_time` button (writes Unix timestamp to device) |

## Installation

### Manual

1. Copy `custom_components/eveus/` to `/config/custom_components/eveus/` on your HA instance.
2. Restart Home Assistant.
3. **Settings → Integrations → Add → Eveus Charger**.

### HACS

The quickest way — click the button below to open the custom-repository dialog pre-filled:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Soundistor&repository=ha-eveus&category=integration)

Or add it manually:

1. Open HACS → **Integrations**.
2. Click the three-dot menu (⋮) in the top-right corner → **Custom repositories**.
3. Enter `https://github.com/Soundistor/ha-eveus` and select category **Integration** → **Add**.
4. Find **Eveus Charger** in the list and click **Download**.
5. Restart Home Assistant.
6. **Settings → Integrations → Add → Eveus Charger**.

## Configuration

| Field | Description |
|-------|-------------|
| IP address | Charger IP (e.g. `192.168.x.x`) |
| Model | `v1` or `v2` |
| Username | Optional (leave blank if not set) |
| Password | Optional (leave blank if not set) |
| Device prefix | Prefix for entity IDs, e.g. `eveus_1` or `eveus_home` |

The **device prefix** determines entity IDs: a prefix of `eveus_1` produces `sensor.eveus_1_state`, `sensor.eveus_1_currentset`, etc. Set it to match your existing automations.

## Entities

### Sensors — both models

| Entity | Unit | Notes |
|--------|------|-------|
| `state` | — | Human-readable charger state |
| `currentset` | A | Configured charging current |
| `curmeas1` | A | Measured charging current |
| `voltmeas1` | V | Measured voltage |
| `powermeas` | W | Charging power |
| `temperature1` | °C | Sensor 1 |
| `temperature2` | °C | Sensor 2 |
| `aistatus` | — | Active AI mode |
| `aivoltage` | V | AI voltage setpoint |
| `curdesign` | A | Design max current |
| `sessiontime` | s | Session duration (raw seconds) |
| `session_time_daily` | h | Charging time since local midnight (resets daily, survives restart) |
| `sessionenergy` | kWh | Energy this session |
| `totalenergy` | kWh | Total energy (cumulative) |
| `energy_daily` | kWh | Charging energy since local midnight (resets daily, survives restart) |
| `systemtime` | — | Charger clock |
| `leakvalue` | mA | Leakage current (diagnostic) |

### Sensors — V2 only

| Entity | Unit | Notes |
|--------|------|-------|
| `substate` | — | Detailed sub-state (limit or error) |
| `vbat` | V | Battery voltage (diagnostic) |
| `rssi` | dBm | Wi-Fi signal (diagnostic) |
| `iem1` | kWh | Energy meter 1 (cumulative) |
| `iem2` | kWh | Energy meter 2 (cumulative) |

### Other entities

| Platform | Entity | Notes |
|----------|--------|-------|
| `switch` | `charging` | Start / stop charging |
| `number` | `current_set` | Charging current setpoint |
| `select` | `ai_mode` | AI mode selector |
| `binary_sensor` | `ground` | Ground connection OK |
| `binary_sensor` | `groundctrl` | Ground protection active |
| `button` | `force_refresh` | Force data update |
| `button` | `sync_time` | Sync charger clock to HA time (V2 only) |

## Services

Besides the entities above, two services are available for automations and scripts:

| Service | Description |
|---------|-------------|
| `eveus.set_current` | Set the charging current, in amperes. |
| `eveus.set_ai_mode` | Set the AI / adaptive power mode. Available modes depend on the model — see the [v1 vs v2 table](#v1-vs-v2-differences). |

Both take the `entity_id` of any entity belonging to the charger.

## Localizations

UI strings are available in Ukrainian (uk), English (en), and Russian (ru).

## Diagnostics

Standard HA diagnostics are supported: **Settings → Integrations → Eveus → Download diagnostics**. IP address, username, and password are redacted in the output.

## Notes

- Polling interval is dynamic: 30 s while charging, 60 s otherwise.
- When the charger is powered off or unplugged, its entities simply become **unavailable** — this is normal and does **not** raise a repair issue. A repair issue is only created when the charger is reachable but returns an error (e.g. wrong credentials, or the configured API version not matching the firmware).
- `ground` and `groundctrl` use debounce (3 consecutive polls) to suppress transient glitches; firmware fault states bypass debounce and trigger immediately.
- `groundctrl` uses value `2` for active (not `1`) — handled correctly.
- All entity names are lowercase to match legacy YAML-based unique IDs and preserve automations.
- The integration ships its own icon (`brand/`), shown automatically on Home Assistant 2026.3+ via the local brands proxy. On older versions the icon requires a submission to [home-assistant/brands](https://github.com/home-assistant/brands).
