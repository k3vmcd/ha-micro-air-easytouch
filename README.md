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

This integration does not currently allow user to control their EasyTouch device from Home Assistant (i.e., this pulls read-only sensor data).

In addition, whenever the manufacturer mobile app connects to the device via bluetooth, Home Assistant will be temporarily disconnected and does not receive data.