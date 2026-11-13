[![GitHub Release](https://img.shields.io/github/release/k3vmcd/ha-micro-air-easytouch.svg?style=flat-square)](https://github.com/k3vmcd/ha-micro-air-easytouch/releases)
[![License](https://img.shields.io/github/license/k3vmcd/ha-micro-air-easytouch.svg?style=flat-square)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz)

# ha-micro-air-easytouch

Home Assistant integration for the Micro-Air EasyTouch RV thermostat, connected over the Micro-Air cloud or Bluetooth Low Energy (BLE).

This integration exposes your EasyTouch thermostat as a native Home Assistant climate entity so you can monitor and control it from the dashboard or from automations. Cloud mode avoids Bluetooth range and single-connection limitations; BLE mode keeps communication local.

## Features

Core:
- Micro-Air cloud connectivity with account thermostat selection and automatic reconnection
- Bluetooth Low Energy connectivity for local control
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
- The same email and password you use to log in to the Micro-Air mobile app; there is no separate integration login

For cloud connections:
- Internet access from Home Assistant and a thermostat already connected to Micro-Air through its 2.4 GHz Wi-Fi network
- Access to the Micro-Air account that owns the thermostat

For Bluetooth connections:
- A Bluetooth adapter or proxy that supports **active (connectable) connections**. The EasyTouch does not advertise its data passively, so any adapter or proxy limited to passive mode will not work, regardless of brand. An ESPHome Bluetooth proxy with `active: true`, a supported USB Bluetooth adapter, or your Home Assistant host's built-in Bluetooth all work.

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

### Micro-Air Cloud

1. Connect the thermostat to Wi-Fi using the official Micro-Air app and confirm it works there.
2. In Home Assistant, go to **Settings > Devices & Services > Add Integration** and search for **Micro-Air EasyTouch**.
3. Choose **Micro-Air Cloud** and enter the same email and password you use in the app.
4. Select the thermostat to add. Accounts with multiple thermostats can repeat setup for each one.

Cloud credentials are stored in the Home Assistant config entry. The integration creates a temporary MQTT certificate when it starts and deletes it when the entry is unloaded; private keys are not saved to disk.

To switch an existing installation between Bluetooth and cloud, open the integration entry's **Reconfigure** action and choose the new connection type. This replaces the previous connection settings while preserving the config entry and all existing entity IDs, names, automations, and dashboards. Cloud connections are validated before the entry is updated.

### Bluetooth Low Energy

1. Go to **Settings > Devices & Services**.
2. Home Assistant should auto-discover the thermostat over Bluetooth and notify you. If not, click **Add Integration**, search for **Micro-Air EasyTouch**, and choose **Bluetooth Low Energy**.
3. Select the discovered device and enter the same email and password you use to sign in to the Micro-Air mobile app.
4. Confirm the discovered device.

Home Assistant creates one climate entity per zone: one for single-zone units, one per zone for multi-zone units. Allow a few minutes after setup for all entities to populate.

## Services

### `micro_air_easytouch.set_location`

Sets the latitude and longitude the thermostat uses to display local weather.

| Field | Description |
|---|---|
| `address` | Optional Bluetooth MAC address or cloud serial number. Leave blank when only one thermostat is configured. |
| `latitude` | Latitude, between -90.0 and 90.0 |
| `longitude` | Longitude, between -180.0 and 180.0 |

With one configured thermostat, no address is needed:

```yaml
service: micro_air_easytouch.set_location
data:
  latitude: 40.7128
  longitude: -74.0060
```

With multiple thermostats, set `address` to the target device's Bluetooth MAC or cloud serial number. This service works over both cloud and Bluetooth connections.

Pairs well with an automation that updates location from a `device_tracker` or `person` entity as the RV moves.

## Troubleshooting

**"Invalid auth" during setup**
Use the same email and password you use to log in to the Micro-Air mobile app. There is no separate password for this integration.

**Cloud setup cannot connect or entities become unavailable**
Verify that Home Assistant has internet access, the thermostat still appears online in the official app, and your network allows outbound connections to Micro-Air's AWS IoT endpoint over MQTT TLS (port 8883). The integration automatically reconnects and requests fresh status after a connection is restored.

**HACS says the repository is invalid**
Make sure **Integration** is selected as the type when you add the custom repository. This is the most common cause of that error.

**The integration can't find or connect to the device**
Your Bluetooth adapter or proxy must support active connections, see Requirements above. A passive-only adapter can see the device advertise but can't complete the connection this integration needs.

**Home Assistant loses connection while using the mobile app**
This is expected. BLE devices only support one active connection at a time, so Home Assistant and the manufacturer's app can't both be connected simultaneously.

## Support

- Questions: [GitHub Discussions](https://github.com/k3vmcd/ha-micro-air-easytouch/discussions)
- Bugs: [GitHub Issues](https://github.com/k3vmcd/ha-micro-air-easytouch/issues)
