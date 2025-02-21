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

from typing import Optional, Any

_LOGGER = logging.getLogger(__name__)


class MicroAirEasyTouchSensor(StrEnum):

    FACE_PLATE_TEMPERATURE = "face_plate_temperature"   
    CURRENT_MODE = "current_mode"
    MODE = "mode"
    # SIGNAL_STRENGTH = "signal_strength"
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
        self.modes = {
            0:"off",
            1:"fan",
            2:"cool",
            3:"cool_on",
            4:"heat",
            5:"heat_on",
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
        
        # # Update signal strength from advertisement
        # self.update_sensor(
        #     key=MicroAirEasyTouchSensor.SIGNAL_STRENGTH,
        #     native_unit_of_measurement="dBm",
        #     native_value=service_info.rssi,
        #     device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        #     name="Signal Strength",
        # )

    def poll_needed(
        self, service_info: BluetoothServiceInfo, last_poll: float | None
    ) -> bool:
        """Determine if polling is needed based on the last poll time."""
        current_time = time.time()
        if last_poll is None:
            _LOGGER.debug("No previous poll, polling now")
            return True
        time_since_last_poll = current_time - last_poll
        _LOGGER.debug("Time since last poll: %s seconds", time_since_last_poll)
        # Poll if connectable or interval exceeded
        return service_info.connectable and time_since_last_poll > UPDATE_INTERVAL
    
    # Function to parse the data from the device
    def decrypt(self, data: bytes) -> bytes:
        status=json.loads(data)
        info=status['Z_sts']['0']
        param=status['PRM']
        modes={0:"off",5:"heat_on",4:"heat",3:"cool_on",2:"cool",1:"fan",11:"auto"}
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
        if self._password is None:
            _LOGGER.debug("Device in initial setup mode - skipping authentication")
            return self._finish_update()

        if not self._password:
            _LOGGER.error("Password not configured")
            return self._finish_update()

        _LOGGER.debug("Connecting to BLE device: %s", ble_device.address)
        self._client = await establish_connection(
            BleakClientWithServiceCache, ble_device, ble_device.address
        )

        if not self._client.is_connected:
            _LOGGER.warning("Failed to connect to BLE device: %s", ble_device.address)
            return self._finish_update()

        try:
            # Authenticate with the device
            if not await self.authenticate(self._password):
                _LOGGER.error("Failed to authenticate with device")
                return self._finish_update()

            _LOGGER.debug("Connected and authenticated to BLE device: %s", ble_device.address)

            # Send the "Get Status" command
            message = {"Type": "Get Status", "Zone": 0, "EM": self._email, "TM": int(time.time())}
            message_json = json.dumps(message)
            await self._client.write_gatt_char(UUIDS["jsonCmd"], bytes(message_json.encode('utf-8')))

            # Wait briefly for the device to process the command (adjust as needed)
            await asyncio.sleep(1)  # Give the device time to respond

            # Read the response from jsonReturn
            json_char = self._client.services.get_characteristic(UUIDS["jsonReturn"])
            json_payload = await self._client.read_gatt_char(json_char)
            decrypted_status = self.decrypt(json_payload.decode('utf-8'))

            # Extract and update sensor data
            face_plate_temperature = decrypted_status.get('facePlateTemperature', 0)
            mode = decrypted_status.get('mode', 'unknown')

            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.FACE_PLATE_TEMPERATURE),
                native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
                native_value=face_plate_temperature,
                device_class=SensorDeviceClass.TEMPERATURE,
                name="Face Plate Temperature",
            )
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.MODE),
                native_unit_of_measurement="",
                native_value=mode,
                name="Mode",
            )

            # Update the current mode
            current_mode = decrypted_status.get('current_mode', 'unknown')
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.CURRENT_MODE),
                native_unit_of_measurement="",
                native_value=current_mode,
                name="Current Mode",
            )

            _LOGGER.debug("Successfully polled device: %s", decrypted_status)
            return self._finish_update()

        except Exception as e:
            _LOGGER.error("Error polling device: %s", str(e))
            raise
        finally:
            if self._client and self._client.is_connected:
                await self._client.disconnect()
            self._event.clear()
            _LOGGER.debug("Disconnected from BLE device")