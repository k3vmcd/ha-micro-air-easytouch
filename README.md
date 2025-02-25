[![GitHub Release](https://img.shields.io/github/release/k3vmcd/ha-micro-air-easytouch.svg?style=flat-square)](https://github.com/k3vmcd/ha-micro-air-easytouch/releases)
[![License](https://img.shields.io/github/license/k3vmcd/ha-micro-air-easytouch.svg?style=flat-square)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-default-orange.svg?style=flat-square)](https://hacs.xyz)

# ha-micro-air-easytouch
Home Assistant Integration for the Micro-Air EasyTouch RV Thermostat

Reads data for the following sensors:
- Faceplate Temperature
- Mode
- Current Mode
- Fan Mode
- Auto Heat Setpoint
- Auto Cool Setpoint
- Heat Setpoint
- Cool Setpoint
- Dry Setpoint

Provides the following controls:
- Reboot Button: Allows you to restart your EasyTouch device

Note: This integration primarily provides read-only sensor data. The reboot button is currently the only control available.

In addition, whenever the manufacturer mobile app connects to the device via bluetooth, Home Assistant will be temporarily disconnected and does not receive data.