[![GitHub Release](https://img.shields.io/github/release/k3vmcd/ha-micro-air-easytouch.svg?style=flat-square)](https://github.com/k3vmcd/ha-micro-air-easytouch/releases)
[![License](https://img.shields.io/github/license/k3vmcd/ha-micro-air-easytouch.svg?style=flat-square)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-default-orange.svg?style=flat-square)](https://hacs.xyz)

# ha-micro-air-easytouch
Home Assistant Integration for the Micro-Air EasyTouch RV Thermostat

This integration implements a Home Assistant climate entity for basic control of your Micro-Air EasyTouch RV thermostat:

Core Features:
- Temperature monitoring via faceplate sensor
- Basic HVAC modes (Heat, Cool, Auto, Dry)
- Fan mode settings
- Temperature setpoint controls

Additional Features:
- Device reboot functionality
- Service to configure device location for the device to display the local weather

Known Limitations:
- The device responds slowly to commands - please wait a few seconds between actions
- When the unit is powered off from the device itself, this state is not reflected in Home Assistant
- Not all fan modes are settable in Home Assistant, "Cycled High" and "Cycled Low" are not available in Home Assistant - this is most likely due to limitations in the Home Assistant Climate entity
- Whenever the manufacturer mobile app connects to the device via bluetooth, Home Assistant will be temporarily disconnected and does not receive data

The integration works through Home Assistant's climate interface. You can control your thermostat through the Home Assistant UI or include it in automations, keeping in mind the device's response limitations.

## Important Upgrade Notice for v0.2.0

**⚠️ REQUIRED ACTION: Full Reinstallation Needed**

If you are upgrading from a version prior to 0.2.0, you must completely uninstall and reinstall the integration. This is due to significant internal changes that improve reliability and add new features.

To upgrade:
1. Remove the integration from Home Assistant (Settings → Devices & Services → Micro-Air EasyTouch → Delete)
2. Restart Home Assistant
3. Install the new version & restart Home Assistant
4. Add the integration again through the UI

## What's New in v0.2.0

- Now uses a Climate entity and is represented as an HVAC device in Home Assistant
- Enhanced Bluetooth connectivity reliability
- Improved error handling and recovery
- Added new service to configure device location

Please note that after upgrading and reconfiguring, you may need to wait a few minutes for all sensors to update and stabilize.