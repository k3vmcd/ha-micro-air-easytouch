from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone

from bleak import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    retry_bluetooth_connection_error,
)
from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from home_assistant_bluetooth import BluetoothServiceInfo
from sensor_state_data import SensorDeviceClass, SensorUpdate, Units
from sensor_state_data.enum import StrEnum

from .const import (
    UUIDS,
    UPDATE_INTERVAL,
)

from typing import Optional

_LOGGER = logging.getLogger(__name__)


class MicroAirEasyTouchSensor(StrEnum):

    FACE_PLATE_TEMPERATURE = "face_plate_temperature"
    CURRENT_MODE_NUMBER = "current_mode_number"
    CURRENT_MODE = "current_mode"
    SIGNAL_STRENGTH = "signal_strength"
    # BATTERY_PERCENT = "battery_percent"
    # TIMESTAMP = "timestamp"

class MicroAirEasyTouchBluetoothDeviceData(BluetoothData):
    """Data for MicroAirEasyTouch sensors."""

    def __init__(self, password: str | None = None, email: str | None = None) -> None:
        """Initialize the data handler."""
        super().__init__()
        self._password = password
        self._email = email
        self._client = None
        self._event = asyncio.Event()
        self._notification_count = 0
        self.modes = {0:"off",3:"cool_on",4:"heat",2:"cool",1:"fan",11:"auto"}

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """Update from BLE advertisement data."""
        _LOGGER.debug("Parsing MicroAirEasyTouch BLE advertisement data: %s", service_info)
        self.set_device_manufacturer("MicroAirEasyTouch")
        self.set_device_type("Thermostat")
        name = f"{service_info.name} {short_address(service_info.address)}"
        self.set_device_name(name)
        self.set_title(name)

    def poll_needed(
        self, service_info: BluetoothServiceInfo, last_poll: float | None
    ) -> bool:
        """
        This is called every time we get a service_info for a device. It means the
        device is working and online.
        """
        _LOGGER.warn("Last poll: %s", last_poll)
        _LOGGER.warn("Update interval: %s", UPDATE_INTERVAL)
        self._notification_count = 0
        return not last_poll or last_poll > UPDATE_INTERVAL

    # @retry_bluetooth_connection_error()
    def notification_handler(self, _, data) -> None:
        """Helper for command events"""
        try:
            face_plate_temperature = data[12]
            current_mode_number = data[15]
            current_mode = self.modes[current_mode_number]


            self.update_sensor(
            key=str(MicroAirEasyTouchSensor.FACE_PLATE_TEMPERATURE),
            native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
            native_value=face_plate_temperature,
            device_class=SensorDeviceClass.TEMPERATURE,
            name="Face Plate Temperature",
            ),
            
            self.update_sensor(
            key=str(MicroAirEasyTouchSensor.CURRENT_MODE),
            native_value=current_mode,
            device_class=SensorDeviceClass.ENUM,
            name="Current Mode",
            )

        except NameError:
            # Handle when variables are not defined
            pass

        # Increment the notification count
        self._notification_count += 1
        _LOGGER.warn("Notification count %s", self._notification_count)
        # Check if all expected notifications are processed
        if self._notification_count >= EXPECTED_NOTIFICATION_COUNT:
            # Reset the counter and set the event to indicate that all notifications are processed
            self._notification_count = 0
            _LOGGER.warn("Notification count %s", self._notification_count)
            self._event.set()
            _LOGGER.warn("Event %s", self._event.is_set())
        return

    async def authenticate(self, password: str) -> bool:
        """Authenticate with the device using password."""
        try:
            # Convert password to bytes and send authentication
            password_bytes = password.encode('utf-8')
            
            await self._client.write_gatt_char(
                UUIDS["strangeCmd"],
                password_bytes,
                response=True
            )
            
            _LOGGER.debug("Authentication sent successfully")
            return True
            
        except Exception as e:
            _LOGGER.error("Authentication failed: %s", str(e))
            return False

    async def connect(self, ble_device: BLEDevice) -> bool:
        """Connect and authenticate with the device."""
        try:
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.address
            )
            
            if await self.authenticate(self._password):
                _LOGGER.info("Successfully connected and authenticated")
                return True
                
            await self._client.disconnect()
            return False
            
        except Exception as e:
            _LOGGER.error("Connection failed: %s", str(e))
            if self._client:
                await self._client.disconnect()
            return False

    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """
        Poll the device to retrieve any values we can't get from passive listening.
        """
        _LOGGER.debug("Connecting to BLE device: %s", ble_device.address)
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, ble_device.address
        )
        try:
            await client.start_notify(
                UUIDS["jsonReturn"], self.notification_handler
            )
            # Wait until all notifications are processed
            try:
                await asyncio.wait_for(self._event.wait(), 15)
            except asyncio.TimeoutError:
                _LOGGER.warn("Timeout waiting for notifications to be processed")
        except:
            _LOGGER.warn("Notify Bleak error")
        finally:
            await client.disconnect()
            self._event.clear()
            _LOGGER.debug("Disconnected from active bluetooth client")
        return self._finish_update()
