# Standard library imports for basic functionality
from __future__ import annotations
import logging
import asyncio
import time
import json

# Bluetooth-related imports for device communication
from bleak import BLEDevice
from bleak.exc import BleakError, BleakDBusError, BleakDeviceNotFoundError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    retry_bluetooth_connection_error,
)

# Home Assistant specific imports for device integration
from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from home_assistant_bluetooth import BluetoothServiceInfo
from sensor_state_data import SensorDeviceClass, SensorUpdate, Units
from sensor_state_data.enum import StrEnum

# Local imports
from .const import (
    UUIDS,
    UPDATE_INTERVAL,
)

from typing import Optional, Any

# Set up logging
_LOGGER = logging.getLogger(__name__)

# Custom retry decorator for handling authentication attempts
from functools import wraps
def retry_authentication(retries=3, delay=1):
    """Custom retry decorator for authentication attempts.
    
    Args:
        retries (int): Number of retry attempts (default: 3)
        delay (int): Delay in seconds between retries (default: 1)
    
    Returns:
        decorator: A decorator that wraps the authentication function with retry logic
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    result = await func(*args, **kwargs)
                    if result:
                        _LOGGER.debug("Authentication successful on attempt %d/%d", 
                                    attempt + 1, retries)
                        return True
                    
                    _LOGGER.debug("Authentication returned False on attempt %d/%d", 
                                attempt + 1, retries)
                    if attempt < retries - 1:
                        _LOGGER.debug("Waiting %d second(s) before retry", delay)
                        await asyncio.sleep(delay)
                        continue
                    
                except Exception as e:
                    last_exception = e
                    _LOGGER.debug(
                        "Authentication attempt %d/%d failed with error: %s", 
                        attempt + 1, 
                        retries, 
                        str(e)
                    )
                    if attempt < retries - 1:
                        _LOGGER.debug("Waiting %d second(s) before retry", delay)
                        await asyncio.sleep(delay)
                        continue
            
            # Final failure logging
            if last_exception:
                _LOGGER.error(
                    "Authentication failed after %d attempts. Last error: %s", 
                    retries, 
                    str(last_exception)
                )
            else:
                _LOGGER.error(
                    "Authentication failed after %d attempts with no exception", 
                    retries
                )
            return False
        return wrapper
    return decorator

class MicroAirEasyTouchSensor(StrEnum):
    """Enumeration of all available sensors for the MicroAir EasyTouch device.
    
    These represent different measurable or controllable aspects of the device.
    """
    
    FACE_PLATE_TEMPERATURE = "face_plate_temperature"   
    CURRENT_MODE = "current_mode"
    MODE = "mode"
    FAN_MODE = "fan_mode"
    AUTO_HEAT_SP = "autoHeat_sp"
    AUTO_COOL_SP = "autoCool_sp"
    COOL_SP = "cool_sp"
    HEAT_SP = "heat_sp"
    DRY_SP = "dry_sp"

class MicroAirEasyTouchBluetoothDeviceData(BluetoothData):
    """Main class for handling MicroAir EasyTouch device data and communication.
    
    This class manages:
    - Device authentication
    - Data parsing
    - Bluetooth communication
    - Sensor updates
    - Error handling and retry logic
    """

    def __init__(self, password: str | None = None, email: str | None = None) -> None:
        """Initialize the device data handler with optional credentials.
        
        Args:
            password: Device authentication password
            email: User email for device commands
        """
        super().__init__()
        self._password = password
        self._email = email
        self._client = None
        self._event = asyncio.Event()
        # Track delays per operation type per device
        self._device_delays = {}  
        self._max_delay = 4.0

    def _get_operation_delay(self, address: str, operation: str) -> float:
        """Calculate delay for specific operations to implement exponential backoff.
        
        Args:
            address: Device bluetooth address
            operation: Type of operation (connect, read, write, auth)
            
        Returns:
            float: Delay time in seconds
        """
        device_delays = self._device_delays.get(address, {})
        return device_delays.get(operation, {}).get('delay', 0.0)

    def _increase_operation_delay(self, address: str, operation: str) -> float:
        """Increase delay for specific operation and device with persistence.
        
        Args:
            address: Device bluetooth address
            operation: Type of operation (connect, read, write, auth)
            
        Returns:
            float: New delay time in seconds
        """
        if address not in self._device_delays:
            self._device_delays[address] = {}
        
        if operation not in self._device_delays[address]:
            self._device_delays[address][operation] = {'delay': 0.0, 'failures': 0}
        
        current = self._device_delays[address][operation]
        current['failures'] += 1
        # Exponential backoff with max limit, persists across polls
        current['delay'] = min(0.5 * (2 ** min(current['failures'], 3)), self._max_delay)  # Cap exponent at 3
        _LOGGER.debug("Increased delay for %s:%s to %.1fs (failures: %d)", 
                      address, operation, current['delay'], current['failures'])
        return current['delay']

    def _adjust_operation_delay(self, address: str, operation: str) -> None:
        """Adjust delay for specific operation after success, reducing gradually.
        
        Args:
            address: Device bluetooth address
            operation: Type of operation (connect, read, write, auth)
        """
        if address in self._device_delays and operation in self._device_delays[address]:
            current = self._device_delays[address][operation]
            if current['failures'] > 0:
                current['failures'] = max(0, current['failures'] - 1)  # Decay failures
                current['delay'] = max(0.0, current['delay'] * 0.75)  # Reduce delay by 25%
                _LOGGER.debug("Adjusted delay for %s:%s to %.1fs (failures: %d)", 
                              address, operation, current['delay'], current['failures'])
            # Don’t reset to 0 unless failures = 0 and delay is small
            if current['failures'] == 0 and current['delay'] < 0.1:
                current['delay'] = 0.0
                _LOGGER.debug("Reset delay for %s:%s to 0.0s", address, operation)

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
        """Parse and decode the device status data.
        
        Converts raw JSON data into a human-readable format with proper
        mode mappings and status information.
        
        Args:
            data: Raw JSON data from device
            
        Returns:
            dict: Decoded device status information
        """
        status=json.loads(data)
        info=status['Z_sts']['0']
        param=status['PRM']
        modes={0:"off",5:"heat_on",4:"heat",3:"cool_on",2:"cool",1:"fan",11:"auto"}
        fan_modes={0:"off",1:"manualL",2:"manualH",65:"cycledL",66:"cycledH",128:"full auto",}
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
    
    @retry_bluetooth_connection_error(attempts=7)
    async def _connect_to_device(self, ble_device: BLEDevice):
        """Connect to the device with retries"""
        try:
            self._client = await establish_connection(
                BleakClientWithServiceCache, 
                ble_device, 
                ble_device.address,
                timeout=20.0
            )

            # Services should be automatically cached by BleakClientWithServiceCache
            _LOGGER.debug("Checking for cached services...")
            
            # Give a moment for services to be available
            if not self._client.services:
                _LOGGER.debug("Waiting for services to be available...")
                await asyncio.sleep(2)

            # Verify services are available
            if not self._client.services:
                _LOGGER.error("No services available after connecting")
                return False

            # Log discovered services and characteristics for debugging
            for service in self._client.services:
                _LOGGER.debug("Service found: %s", service.uuid)
                for char in service.characteristics:
                    _LOGGER.debug("  Characteristic: %s", char.uuid)

            return self._client

        except Exception as e:
            _LOGGER.error("Connection error: %s", str(e))
            raise
    
    @retry_authentication(retries=3, delay=2)
    async def authenticate(self, password: str) -> bool:
        """Authenticate with the device using the provided password.
        
        Implements retry logic and proper connection handling.
        
        Args:
            password: Device authentication password
            
        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            # Ensure client exists and is connected and wait if not
            if not self._client or not self._client.is_connected:
                _LOGGER.warning("Client not connected during authentication - attempting to wait for connection to be made")
                await asyncio.sleep(1)
                if not self._client or not self._client.is_connected:
                    _LOGGER.error("Client not connected when attempting authentication. Reconnecting now...")
                    await self._connect_to_device(self._ble_device)
                    await asyncio.sleep(0.5)
                if not self._client or not self._client.is_connected:
                    _LOGGER.error("Client not connected after reconnecting. Authentication failed.")
                    return False
            
            # Ensure services are discovered
            if not self._client.services:
                _LOGGER.debug("Services were not discovered when attempting authentication. Discovering services...")
                await self._client.discover_services()
                await asyncio.sleep(1)  # Give device time to process
                if not self._client.services:
                    _LOGGER.error("Services not discovered after waiting. Authentication step failed.")
                    return False

            # Convert password to bytes and send authentication with retry
            password_bytes = password.encode('utf-8')
            try:
                await self._client.write_gatt_char(
                    UUIDS["strangeCmd"],
                    password_bytes,
                    response=True
                )
            except BleakError as e:
                if "connection status" in str(e):
                    _LOGGER.debug("Connection dropped during authentication, will retry")
                    return False
                raise

            _LOGGER.debug("Authentication sent successfully")
            return True
                
        except Exception as e:
            _LOGGER.error("Authentication failed: %s", str(e), exc_info=True)
            # Ensure client is disconnected on error
            if self._client and self._client.is_connected:
                await self._client.disconnect()
            self._client = None
            return False

    async def _write_gatt_with_retry(self, uuid: str, data: bytes, ble_device: BLEDevice, retries: int = 3) -> bool:
        """Write GATT characteristic with retry and adaptive delay."""
        last_error = None
        for attempt in range(retries):
            try:
                if not self._client or not self._client.is_connected:
                    if not await self._reconnect_and_authenticate(ble_device):
                        return False

                # Apply write-specific delay if needed
                write_delay = self._get_operation_delay(ble_device.address, 'write')
                if write_delay > 0:
                    await asyncio.sleep(write_delay)

                await self._client.write_gatt_char(uuid, data, response=True)
                self._adjust_operation_delay(ble_device.address, 'write')
                return True

            except BleakError as e:
                last_error = e
                if attempt < retries - 1:
                    delay = self._increase_operation_delay(ble_device.address, 'write')
                    _LOGGER.debug(
                        "GATT write failed for %s, attempt %d/%d. Using delay: %.1f", 
                        ble_device.address, attempt + 1, retries, delay
                    )
                    continue

        _LOGGER.error("GATT write failed after %d attempts. Last error: %s", 
                    retries, str(last_error))
        return False

    async def _reconnect_and_authenticate(self, ble_device: BLEDevice) -> bool:
        """Reconnect and re-authenticate with adaptive delays."""
        try:
            # Apply connect-specific delay if needed
            connect_delay = self._get_operation_delay(ble_device.address, 'connect')
            if connect_delay > 0:
                await asyncio.sleep(connect_delay)

            _LOGGER.debug("Attempting reconnection for device: %s", ble_device.address)
            self._client = await self._connect_to_device(ble_device)
            
            if not self._client or not self._client.is_connected:
                self._increase_operation_delay(ble_device.address, 'connect')
                return False
            
            self._adjust_operation_delay(ble_device.address, 'connect')
            
            # Apply auth-specific delay if needed
            auth_delay = self._get_operation_delay(ble_device.address, 'auth')
            if auth_delay > 0:
                await asyncio.sleep(auth_delay)

            auth_result = await self.authenticate(self._password)
            
            if auth_result:
                self._adjust_operation_delay(ble_device.address, 'auth')
            else:
                self._increase_operation_delay(ble_device.address, 'auth')
            
            return auth_result

        except Exception as e:
            _LOGGER.error("Reconnection failed: %s", str(e))
            self._increase_operation_delay(ble_device.address, 'connect')
            return False

    async def _read_gatt_with_retry(self, characteristic, ble_device: BLEDevice, retries: int = 3) -> Optional[bytes]:
        """Read GATT characteristic with retry and operation-specific delay."""
        last_error = None
        for attempt in range(retries):
            try:
                if not self._client or not self._client.is_connected:
                    if not await self._reconnect_and_authenticate(ble_device):
                        return None

                # Apply read-specific delay if needed
                read_delay = self._get_operation_delay(ble_device.address, 'read')
                if read_delay > 0:
                    await asyncio.sleep(read_delay)

                result = await self._client.read_gatt_char(characteristic)
                self._adjust_operation_delay(ble_device.address, 'read')
                return result

            except BleakError as e:
                last_error = e
                if attempt < retries - 1:
                    delay = self._increase_operation_delay(ble_device.address, 'read')
                    _LOGGER.debug(
                        "GATT read failed for %s, attempt %d/%d. Using delay: %.1f", 
                        ble_device.address, attempt + 1, retries, delay
                    )
                    continue

        _LOGGER.error("GATT read failed after %d attempts. Last error: %s", 
                    retries, str(last_error))
        return None

    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """Main polling function to retrieve current device state.
        
        This method:
        1. Connects to the device
        2. Authenticates
        3. Retrieves current status
        4. Updates all sensor values
        5. Properly disconnects
        
        Args:
            ble_device: The bluetooth device to poll
            
        Returns:
            SensorUpdate: Updated sensor values for Home Assistant
        """
        if self._password is None:
            _LOGGER.debug("Device in initial setup mode - skipping authentication")
            return self._finish_update()

        if not self._password:
            _LOGGER.error("Password not configured")
            return self._finish_update()
        
        try:
            _LOGGER.debug("Connecting to BLE device: %s", ble_device.address)
            self._client = await self._connect_to_device(ble_device)

            if not self._client or not self._client.is_connected:
                _LOGGER.warning("Failed to connect to BLE device: %s", ble_device.address)
                return self._finish_update()
            
            _LOGGER.debug("Connection established, client connected: %s", self._client.is_connected)
            _LOGGER.debug("Device address: %s", ble_device.address)
            _LOGGER.debug("Device details: %s", ble_device.details)

            # Authenticate with the device
            if not await self.authenticate(self._password):
                _LOGGER.error("Failed to authenticate with device")
                return self._finish_update()

            _LOGGER.debug("Connected and authenticated to BLE device: %s", ble_device.address)

            # Send status command with retry and log payload
            message = {"Type": "Get Status", "Zone": 0, "EM": self._email, "TM": int(time.time())}
            payload = bytes(json.dumps(message).encode('utf-8'))
            _LOGGER.debug("Writing to jsonCmd: %s", payload.hex())
            if not await self._write_gatt_with_retry(
                UUIDS["jsonCmd"], 
                payload,
                ble_device
            ):
                return self._finish_update()

            # Read response with retry and log response
            json_char = self._client.services.get_characteristic(UUIDS["jsonReturn"])
            json_payload = await self._read_gatt_with_retry(json_char, ble_device)
            _LOGGER.debug("Read from jsonReturn: %s", json_payload.hex() if json_payload else "None")
            if not json_payload:
                return self._finish_update()
            decrypted_status = self.decrypt(json_payload.decode('utf-8'))

            # SENSOR UPDATES

            # Update the face plate temperature
            face_plate_temperature = decrypted_status.get('facePlateTemperature', 0)
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.FACE_PLATE_TEMPERATURE),
                native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
                native_value=face_plate_temperature,
                device_class=SensorDeviceClass.TEMPERATURE,
                name="Face Plate Temperature",
            )

            # Update the mode
            mode = decrypted_status.get('mode', 'unknown')
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

            # Update the fan mode
            fan_mode = decrypted_status.get('fan_mode', 'unknown')
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.FAN_MODE),
                native_unit_of_measurement="",
                native_value=fan_mode,
                name="Fan Mode",
            )

            # Update the Auto Heat Setpoint
            auto_heat_sp = decrypted_status.get('autoHeat_sp', 0)
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.AUTO_HEAT_SP),
                native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
                native_value=auto_heat_sp,
                name="Auto Heat Setpoint",
            )

            # Update the Auto Cool Setpoint
            auto_cool_sp = decrypted_status.get('autoCool_sp', 0)
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.AUTO_COOL_SP),
                native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
                native_value=auto_cool_sp,
                name="Auto Cool Setpoint",
            )

            # Update the Cool Setpoint
            cool_sp = decrypted_status.get('cool_sp', 0)
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.COOL_SP),
                native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
                native_value=cool_sp,
                name="Cool Setpoint",
            )

            # Update the Heat Setpoint
            heat_sp = decrypted_status.get('heat_sp', 0)
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.HEAT_SP),
                native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
                native_value=heat_sp,
                name="Heat Setpoint",
            )

            # Update the Dry Setpoint
            dry_sp = decrypted_status.get('dry_sp', 0)
            self.update_sensor(
                key=str(MicroAirEasyTouchSensor.DRY_SP),
                native_unit_of_measurement=Units.TEMP_FAHRENHEIT,
                native_value=dry_sp,
                name="Dry Setpoint",
            )

            _LOGGER.debug("Successfully polled device: %s", decrypted_status)
            return self._finish_update()

        except BleakDBusError as e:
            _LOGGER.error("D-Bus error connecting to device: %s", str(e))
            return self._finish_update()
        except BleakError as e:
            _LOGGER.error("Bluetooth error connecting to device: %s", str(e))
            return self._finish_update()
        except Exception as e:
            _LOGGER.error("Error polling device: %s", str(e))
            raise
        finally:
            try:
                if self._client and self._client.is_connected:
                    await self._client.disconnect()
            except Exception as e:
                _LOGGER.debug("Error disconnecting: %s", str(e))
            self._client = None
            self._event.clear()
            _LOGGER.debug("Disconnected from BLE device")