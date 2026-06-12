# Eveus Charger for Home Assistant

Custom integration for Eveus EV chargers (API v1 and v2).

## Supported devices

| API version | Fields | Min current |
|-------------|--------|-------------|
| v1 | 41 | 7 A |
| v2 | 97 | 6 A |

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
| Device prefix | Prefix for entity IDs, e.g. `gbt_eveus` or `evse_eveus` |

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
| `sessiontime` | s | Session duration (raw seconds) |
| `newsessiontime` | — | Session duration formatted HH:MM:SS |
| `sessionenergy` | kWh | Energy this session |
| `totalenergy` | kWh | Total energy (cumulative) |
| `systemtime` | — | Charger clock |
| `leakvalue` | mA | Leakage current (diagnostic) |

### Sensors — V2 only

| Entity | Unit | Notes |
|--------|------|-------|
| `substate` | — | Detailed sub-state (limit or error) |
| `curdesign` | A | Design max current |
| `vbat` | V | Battery voltage (diagnostic) |
| `rssi` | dBm | Wi-Fi signal (diagnostic) |
| `iem1` | kWh | Energy meter 1 (cumulative) |
| `iem2` | kWh | Energy meter 2 (cumulative) |

### Other entities

| Platform | Entity | Notes |
|----------|--------|-------|
| `switch` | `enabled` | Start / stop charging |
| `number` | `current_set` | Charging current setpoint |
| `select` | `ai_mode` | AI mode selector |
| `binary_sensor` | `ground` | Ground connection OK |
| `binary_sensor` | `groundctrl` | Ground protection active |
| `button` | `force_refresh` | Force data update |
| `button` | `sync_time` | Sync charger clock to HA time (V2 only) |

## Notes

- **API v1** `evseEnabled=1` means charging active; **API v2** `evseEnabled=0` means charging active.
- `groundctrl` uses value `2` for active (not `1`) — handled correctly.
- All entity names are lowercase to match legacy YAML-based unique IDs and preserve automations.
