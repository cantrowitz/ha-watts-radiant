# Watts Radiant for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cantrowitz&repository=ha-watts-radiant&category=integration)

A native Home Assistant custom component for **Watts Radiant floor heating**,
powered by the **Watts Home** app backend.

Connects directly to the Watts cloud using your standard Watts Home app
credentials (email and password) — no extra hardware, MQTT broker, or
Bluetooth bridges required.

---

## Features

- **Native UI Config Flow**: Log in directly with your Watts Home credentials
  from *Settings > Devices & Services*.
- **Automatic Location Discovery**: Automatically detects your Watts location
  (e.g. *801*) and its thermostats, grouped under that location.
- **Climate Control**:
  - **Thermostat** (`climate.<thermostat_name>`): Mode Off / Heat, target
    temperature, current temperature following the thermostat's target
    sensor (floor or room), and heating / idle / off action.
  - **Presets**: *Schedule* (following the thermostat schedule) and *Hold*
    (a temperature override). Selecting *Schedule* cancels an override.
- **Temperature Sensors**:
  - **Floor temperature** (`sensor.<thermostat_name>_floor_temperature`)
  - **Room temperature** (`sensor.<thermostat_name>_room_temperature`)
- **Schedule Switch** (`switch.<thermostat_name>_schedule`): Turn a
  thermostat's schedule on or off.
- **Away Mode** (`switch.<location_name>_away_mode`): Toggle a location
  between Home (off) and Away (on).
- **Home/Away** (`sensor.<location_name>_home_away`): The current mode,
  stated explicitly as *Home* or *Away*, paired with the switch above.
- **Location Grouping**: Thermostats are nested under their location as
  child devices (Home Assistant 2026.9+), so the location's device page
  lists its thermostats as sub-devices.

---

## Compatibility & Limitations

- **Developed and tested with SunTouch SunstatGen4 thermostats** in two
  bathrooms under a single location. Other Watts Radiant / SunTouch
  thermostats are expected to work, but have not been tested yet —
  issue reports with your model and a debug log are very welcome.
- **Cloud polling**: the integration talks to the Watts cloud (the same
  backend as the Watts Home app) using your app account credentials, polling
  every 60 seconds. There is no local control; if the cloud or your
  internet connection is down, control is unavailable.
- **Child-device display**: as child devices, thermostats in Home Assistant
  show their parent location's manufacturer and model in the device info
  card, rather than their own SunTouch / SunstatGen4 details. That is how
  Home Assistant models child devices.
- **Not all Watts Home app features are covered** (e.g. full schedule
  editing is not currently supported — the schedule itself is read and
  can be turned on or off, but not edited from Home Assistant).

---

## Installation

### Method 1: Via HACS (Recommended)

1. Open **HACS** in your Home Assistant dashboard.
2. Click the three dots in the top-right corner and select **Custom repositories**.
3. Enter the repository URL:

```
https://github.com/cantrowitz/ha-watts-radiant
```

4. Select category **Integration** and click **Add**.
5. Find **Watts Radiant** in HACS and click **Download**.
6. Restart Home Assistant.

### Method 2: Manual Installation

1. Download the latest release from the Releases page and unzip it
   (release zips contain the integration files at the top level).
2. Copy the files into a `watts_radiant` directory under your Home Assistant
   `<config_dir>/custom_components/` directory:

```
config/
└── custom_components/
    └── watts_radiant/
        ├── __init__.py
        ├── api.py
        ├── brand/
        │   ├── icon.png
        │   └── icon@2x.png
        ├── climate.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── entity.py
        ├── manifest.json
        ├── models.py
        ├── sensor.py
        ├── strings.json
        ├── switch.py
        └── translations/
            └── en.json
```

3. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to **Settings** > **Devices & Services**.
2. Click **Add Integration** in the bottom-right corner.
3. Search for **Watts Radiant**.
4. Enter your Watts Home **Email** and **Password**.
5. Click **Submit**!

---

## Discovering Entities & Telemetry (Debug Logging)

To see the raw API responses and poll results, enable debug logging in your
`configuration.yaml`:

```
logger:
  default: info
  logs:
    custom_components.watts_radiant: debug
```

Check your logs under **Settings** > **System** > **Logs**.

---

## Disclaimer

This custom integration is not affiliated with, endorsed by, or associated
with Watts or SunTouch. All product names, logos, and brands are property
of their respective owners.
