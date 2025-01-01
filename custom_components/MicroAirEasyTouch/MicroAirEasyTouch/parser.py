from __future__ import annotations

import logging
import asyncio
import time
import json
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
        # self._notification_count = 0
        self.modes = {
            0:"off",
            1:"fan",
            2:"cool",
            3:"cool_on",
            4:"heat",
            11:"auto"
            }

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
        # _LOGGER.warn("Last poll: %s", last_poll)
        # _LOGGER.warn("Update interval: %s", UPDATE_INTERVAL)
        # self._notification_count = 0
        return not last_poll or last_poll > UPDATE_INTERVAL

    # @retry_bluetooth_connection_error()
    def notification_handler(self, _, data) -> None:
        """Helper for command events"""
        try:
            # face_plate_temperature = data[12]
            current_mode_number = data[15]
            # current_mode = self.modes[current_mode_number]

        except NameError:
            # Handle when variables are not defined
            pass

# Removing the notification counter and just setting the event after a single notification
#
#         # Increment the notification count
#         self._notification_count += 1
#         _LOGGER.warn("Notification count %s", self._notification_count)
#         # Check if all expected notifications are processed
#         if self._notification_count >= EXPECTED_NOTIFICATION_COUNT:
#             # Reset the counter and set the event to indicate that all notifications are processed
#             self._notification_count = 0
#             _LOGGER.warn("Notification count %s", self._notification_count)
#             self._event.set()
#             _LOGGER.warn("Event %s", self._event.is_set())
#
        # Set the event to indicate that the notification is processed
        self._event.set()
        return
    
    # Function to parse the data from the device
    def decrypt(self, data: bytes) -> bytes:
        status=json.loads(data)
        info=status['Z_sts']['0']
        param=status['PRM']
        modes={0:"off",3:"cool_on",4:"heat",2:"cool",1:"fan",11:"auto"}
        fan_modes={0:"off",1:"manuelL",2:"manuellH",65:"cycledL",66:"cycledH",128:"full auto",}
        hr_status={}
        hr_status['SN']=status['SN']
        hr_status['autoHeat_sp']=info[0]
        hr_status['autoCool_sp']=info[1]
        hr_status['cool_sp']=info[2]
        hr_status['heat_sp']=info[3]
        hr_status['dry_sp']=info[4]
        hr_status['u5']=info[5]
        hr_status['fan_mode_num']=info[6]
        hr_status['cool_mode_num']=info[7]
        hr_status['u8']=info[8]
        hr_status['u9']=info[9]
        hr_status['mode_num']=info[10]
        hr_status['heat_mode_num']=info[11]
        hr_status['facePlateTemperature']=info[12]
        hr_status['u13']=info[13]
        hr_status['u14']=info[14]
        hr_status['current_mode_num']=info[15]
        hr_status['ALL']=status
        if 7 in param:
            hr_status['off']=True
        if 15 in param:
            hr_status['on']=True
        
        if  hr_status['current_mode_num'] in modes:
            hr_status['current_mode']=modes[hr_status['current_mode_num']]
        if  hr_status['mode_num'] in modes:
            hr_status['mode']=modes[hr_status['mode_num']]
        if  hr_status['fan_mode_num'] in fan_modes:
            hr_status['fan_mode']=fan_modes[hr_status['fan_mode_num']]
        if  hr_status['cool_mode_num'] in fan_modes:
            hr_status['cool_mode']=fan_modes[hr_status['cool_mode_num']]
        if  hr_status['heat_mode_num'] in fan_modes:
            hr_status['heat_mode']=fan_modes[hr_status['heat_mode_num']]
        return hr_status
    
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
        
    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """Poll the device to retrieve sensor values."""
        # During initial setup, password is intentionally None
        if self._password is None:
            _LOGGER.debug("Device in initial setup mode - skipping authentication")
            return self._finish_update()

        # Normal operation with configured password
        if not self._password:
            _LOGGER.error("Password not configured")
            return self._finish_update()

        _LOGGER.debug("Connecting to BLE device: %s", ble_device.address)
        self._client = await establish_connection(
            BleakClientWithServiceCache, ble_device, ble_device.address
        )

        try:
            # Authenticate to the device
            if not await self.authenticate(self._password):
                _LOGGER.error("Failed to authenticate with device")
                return self._finish_update()

            _LOGGER.debug("Connected and authenticated to BLE device: %s", ble_device.address)

            # Start listening for response
            json_char = self._client.services.get_characteristic(UUIDS["jsonReturn"])
            json_payload = await self._client.read_gatt_char(json_char)

            # Send the Get Status command
            message = {"Type":"Get Status","Zone":0,"EM":self._email,"TM":int(time.time())}
            message_json = json.dumps(message)
            await self._client.write_gatt_char(UUIDS["jsonCmd"], bytes(message_json.encode('utf_8')))

            # Send the response to the decrypt function
            status = self.decrypt(bytes(json_payload).decode())

            # Prepare the decrypted data for sensor updates
            face_plate_temperature = status['facePlateTemperature']
            current_mode = status['current_mode']

            # Update the sensors
            self.update_sensor(
            key=str(MicroAirEasyTouchSensor.FACE_PLATE_TEMPERATURE),
            native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
            native_value=face_plate_temperature,
            device_class=SensorDeviceClass.TEMPERATURE,
            name="Face Plate Temperature",
            ),
            
            self.update_sensor(
            key=str(MicroAirEasyTouchSensor.CURRENT_MODE),
            native_unit_of_measurement="",  # Empty string for mode data
            native_value=current_mode,
            name="Current Mode",
            )

            # Wait to see if a callback comes in.
            try:
                await asyncio.wait_for(self._event.wait(), 15)
            except asyncio.TimeoutError:
                _LOGGER.warn("Timeout getting command data.")
            except:
                _LOGGER.warn("Wait For Bleak error")
            finally:
                await self._client.stop_notify(UUIDS["jsonReturn"])
                await self._client.disconnect()
                _LOGGER.debug("Disconnected from active bluetooth client")
            return self._finish_update()

        except Exception as e:
            _LOGGER.error("Error polling device: %s", str(e))
            raise
        finally:
            if self._client:
                await self._client.disconnect()
                self._event.clear()