"""Parser for MicroAirEasyTouch advertisements"""
from __future__ import annotations

from sensor_state_data import (
    BinarySensorDeviceClass,
    BinarySensorValue,
    DeviceKey,
    SensorDescription,
    SensorDeviceClass,
    SensorDeviceInfo,
    SensorUpdate,
    SensorValue,
    Units,
)

from .parser import MicroAirEasyTouchBluetoothDeviceData, MicroAirEasyTouchSensor

__version__ = "0.1.0"

__all__ = [
    "MicroAirEasyTouchSensor",
    "MicroAirEasyTouchBluetoothDeviceData",
    "BinarySensorDeviceClass",
    "DeviceKey",
    "SensorUpdate",
    "SensorDeviceClass",
    "SensorDeviceInfo",
    "SensorValue",
    "Units",
]
