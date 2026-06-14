# Eveus Charger for Home Assistant

Custom integration for Eveus EV chargers (API v1 and v2).

## Supported devices

| API version | Min current | JSON fields |
|-------------|-------------|-------------|
| v1 | 7 A | 41 |
| v2 | 6 A | 97 |

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

## Localizations

UI strings are available in English, Russian (ru), and Ukrainian (uk).

## Diagnostics

Standard HA diagnostics are supported: **Settings → Integrations → Eveus → Download diagnostics**. IP address, username, and password are redacted in the output.

## Notes

- Polling interval is dynamic: 30 s while charging, 60 s otherwise.
- `ground` and `groundctrl` use debounce (3 consecutive polls) to suppress transient glitches; firmware fault states bypass debounce and trigger immediately.
- `groundctrl` uses value `2` for active (not `1`) — handled correctly.
- All entity names are lowercase to match legacy YAML-based unique IDs and preserve automations.
- The integration ships its own icon (`brand/`), shown automatically on Home Assistant 2026.3+ via the local brands proxy. On older versions the icon requires a submission to [home-assistant/brands](https://github.com/home-assistant/brands).
