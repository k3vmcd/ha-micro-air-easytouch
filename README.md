[![GitHub Release](https://img.shields.io/github/release/k3vmcd/ha-micro-air-easytouch.svg?style=flat-square)](https://github.com/k3vmcd/ha-micro-air-easytouch/releases)
[![License](https://img.shields.io/github/license/k3vmcd/ha-micro-air-easytouch.svg?style=flat-square)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz)

# ha-micro-air-easytouch

Home Assistant integration for the Micro-Air EasyTouch RV thermostat, connected over Bluetooth Low Energy (BLE).

This integration exposes your EasyTouch thermostat as a native Home Assistant climate entity so you can monitor and control it from the dashboard or from automations.

## Features

Core:
- Climate entity per zone (temperature, HVAC mode, fan mode, setpoints)
- Automatic multi-zone detection, single-zone and multi-zone units are both supported
- Ambient temperature sensor from the faceplate
- HVAC modes: Heat, Cool, Auto, Dry
- Fan modes: Off, Low, High, Auto (where supported by the current HVAC mode)

Additional:
- Reboot button for the thermostat
- `set_location` service so the device can display local weather

Known limitations:
- When the unit is powered off from the device itself, this state is not reflected in Home Assistant
- Not all fan modes are settable in Home Assistant, "Cycled High" and "Cycled Low" are not available in Home Assistant - this is due to limitations in the Home Assistant Climate entity
- Whenever the manufacturer mobile app connects to the device via bluetooth, Home Assistant will be temporarily disconnected and does not receive data

## Requirements

- Home Assistant 2024.10.1 or newer
- A Bluetooth adapter or proxy that supports **active (connectable) connections**. The EasyTouch does not advertise its data passively, so any adapter or proxy limited to passive mode will not work, regardless of brand. An ESPHome Bluetooth proxy with `active: true`, a supported USB Bluetooth adapter, or your Home Assistant host's built-in Bluetooth all work.
- The same email and password you use to log in to the Micro-Air mobile app, there is no separate integration login.

## Installation

### Option 1: HACS (recommended)

This repository is not yet in the HACS default store, so it needs to be added as a custom repository:

1. In Home Assistant, open **HACS**
2. Click the three-dot menu in the top right corner and choose **Custom repositories**
3. Add the repository URL: `https://github.com/k3vmcd/ha-micro-air-easytouch`
4. Set **Type** to **Integration** (required, otherwise HACS reports the repository as invalid)
5. Click **Add**
6. Find **Micro-Air EasyTouch Thermostat** in HACS and click **Download**
7. Restart Home Assistant

### Option 2: Manual installation

1. Download the latest release from the [Releases page](https://github.com/k3vmcd/ha-micro-air-easytouch/releases)
2. Copy the `custom_components/micro_air_easytouch` folder into the `custom_components` folder of your Home Assistant configuration directory (create the folder if it doesn't exist)
3. Restart Home Assistant

## Setup

1. Go to **Settings > Devices & Services**
2. Home Assistant should auto-discover the thermostat over Bluetooth and notify you. If not, click **Add Integration** and search for **Micro-Air EasyTouch**
3. When prompted for credentials, enter the same email and password you use to sign in to the Micro-Air mobile app
4. Confirm the discovered device

Home Assistant creates one climate entity per zone: one for single-zone units, one per zone for multi-zone units.

Allow a few minutes after setup for all entities to populate.

## Services

### `micro_air_easytouch.set_location`

Sets the latitude and longitude the thermostat uses to display local weather.

| Field | Description |
|---|---|
| `address` | Bluetooth MAC address of the thermostat, e.g. `00:11:22:33:44:55` |
| `latitude` | Latitude, between -90.0 and 90.0 |
| `longitude` | Longitude, between -180.0 and 180.0 |

Example:

```yaml
service: micro_air_easytouch.set_location
data:
  address: "00:11:22:33:44:55"
  latitude: 40.7128
  longitude: -74.0060
```

Pairs well with an automation that updates location from a `device_tracker` or `person` entity as the RV moves.

## Troubleshooting

**"Invalid auth" during setup**
Use the same email and password you use to log in to the Micro-Air mobile app. There is no separate password for this integration.

**HACS says the repository is invalid**
Make sure **Integration** is selected as the type when you add the custom repository. This is the most common cause of that error.

**The integration can't find or connect to the device**
Your Bluetooth adapter or proxy must support active connections, see Requirements above. A passive-only adapter can see the device advertise but can't complete the connection this integration needs.

**Home Assistant loses connection while using the mobile app**
This is expected. BLE devices only support one active connection at a time, so Home Assistant and the manufacturer's app can't both be connected simultaneously.

## Support

- Questions: [GitHub Discussions](https://github.com/k3vmcd/ha-micro-air-easytouch/discussions)
- Bugs: [GitHub Issues](https://github.com/k3vmcd/ha-micro-air-easytouch/issues)
