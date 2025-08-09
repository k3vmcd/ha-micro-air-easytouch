# Standard library imports for basic functionality
from __future__ import annotations
import logging
import asyncio
import time
import json

# Bluetooth-related imports for device communication
from bleak import BLEDevice
from bleak.exc import BleakError, BleakDBusError
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

from ..const import DOMAIN
from .const import UUIDS

_LOGGER = logging.getLogger(__name__)

from functools import wraps
def retry_authentication(retries=3, delay=1):
    """Custom retry decorator for authentication attempts."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    result = await func(*args, **kwargs)
                    if result:
                        _LOGGER.debug("Authentication successful on attempt %d/%d", attempt + 1, retries)
                        return True
                    _LOGGER.debug("Authentication returned False on attempt %d/%d", attempt + 1, retries)
                    if attempt < retries - 1:
                        await asyncio.sleep(delay)
                        continue
                except Exception as e:
                    last_exception = e
                    _LOGGER.debug("Authentication attempt %d/%d failed: %s", attempt + 1, retries, str(e))
                    if attempt < retries - 1:
                        await asyncio.sleep(delay)
                        continue
            if last_exception:
                _LOGGER.error("Authentication failed after %d attempts: %s", retries, str(last_exception))
            else:
                _LOGGER.error("Authentication failed after %d attempts with no exception", retries)
            return False
        return wrapper
    return decorator

class MicroAirEasyTouchSensor(StrEnum):
    """Enumeration of all available sensors for the MicroAir EasyTouch device."""
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
    """Main class for handling MicroAir EasyTouch device data and communication."""

    def __init__(self, password: str | None = None, email: str | None = None) -> None:
        """Initialize the device data handler with optional credentials."""
        super().__init__()
        self._password = password
        self._email = email
        self._client = None
        self._max_delay = 6.0
        self._notification_task = None

    def _get_operation_delay(self, hass, address: str, operation: str) -> float:
        """Calculate delay for specific operations from persistent storage."""
        device_delays = hass.data.setdefault(DOMAIN, {}).setdefault('device_delays', {}).get(address, {})
        return device_delays.get(operation, {}).get('delay', 0.0)

    def _increase_operation_delay(self, hass, address: str, operation: str) -> float:
        """Increase delay for specific operation and device with persistence."""
        delays = hass.data.setdefault(DOMAIN, {}).setdefault('device_delays', {})
        if address not in delays:
            delays[address] = {}
        if operation not in delays[address]:
            delays[address][operation] = {'delay': 0.0, 'failures': 0}
        current = delays[address][operation]
        current['failures'] += 1
        current['delay'] = min(0.5 * (2 ** min(current['failures'], 3)), self._max_delay)
        _LOGGER.debug("Increased delay for %s:%s to %.1fs (failures: %d)", address, operation, current['delay'], current['failures'])
        return current['delay']

    def _adjust_operation_delay(self, hass, address: str, operation: str) -> None:
        """Adjust delay for specific operation after success, reducing gradually."""
        delays = hass.data.setdefault(DOMAIN, {}).setdefault('device_delays', {})
        if address in delays and operation in delays[address]:
            current = delays[address][operation]
            if current['failures'] > 0:
                current['failures'] = max(0, current['failures'] - 1)
                current['delay'] = max(0.0, current['delay'] * 0.75)
                _LOGGER.debug("Adjusted delay for %s:%s to %.1fs (failures: %d)", address, operation, current['delay'], current['failures'])
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

    def decrypt(self, data: bytes) -> dict:
        """Parse and decode the device status data."""
        status = json.loads(data)
        param = status['PRM']
        modes = {0: "off", 5: "heat_on", 4: "heat", 3: "cool_on", 2: "cool", 1: "fan", 11: "auto"}
        fan_modes_full = {0: "off", 1: "manualL", 2: "manualH", 65: "cycledL", 66: "cycledH", 128: "full auto"}
        fan_modes_fan_only = {0: "off", 1: "low", 2: "high"}
        
        hr_status = {}
        hr_status['SN'] = status['SN']
        hr_status['ALL'] = status
        
        # Detect available zones and process each one
        available_zones = []
        zone_data = {}
        
        for zone_key in status['Z_sts'].keys():
            zone_num = int(zone_key)
            available_zones.append(zone_num)
            info = status['Z_sts'][zone_key]
            
            zone_status = {}
            zone_status['autoHeat_sp'] = info[0]
            zone_status['autoCool_sp'] = info[1]
            zone_status['cool_sp'] = info[2]
            zone_status['heat_sp'] = info[3]
            zone_status['dry_sp'] = info[4]
            zone_status['fan_mode_num'] = info[6]  # Fan setting in fan-only mode
            zone_status['cool_fan_mode_num'] = info[7]  # Fan setting in cool mode
            zone_status['auto_fan_mode_num'] = info[9]  # Fan setting in auto mode
            zone_status['mode_num'] = info[10]
            zone_status['heat_fan_mode_num'] = info[11]  # Fan setting in heat mode
            zone_status['facePlateTemperature'] = info[12]
            zone_status['current_mode_num'] = info[15]

            if 7 in param:
                zone_status['off'] = True
            if 15 in param:
                zone_status['on'] = True

            # Map modes
            if zone_status['current_mode_num'] in modes:
                zone_status['current_mode'] = modes[zone_status['current_mode_num']]
            if zone_status['mode_num'] in modes:
                zone_status['mode'] = modes[zone_status['mode_num']]

            # Map fan modes based on current mode
            current_mode = zone_status.get('mode', "off")
            
            # Store the raw fan mode numbers and their string representations
            if current_mode == "fan":
                fan_num = info[6]
                zone_status['fan_mode_num'] = fan_num
                zone_status['fan_mode'] = fan_modes_fan_only.get(fan_num, "off")
            elif current_mode == "cool":
                fan_num = info[7]
                zone_status['cool_fan_mode_num'] = fan_num
                zone_status['cool_fan_mode'] = fan_modes_full.get(fan_num, "full auto")
            elif current_mode == "heat":
                fan_num = info[11]
                zone_status['heat_fan_mode_num'] = fan_num
                zone_status['heat_fan_mode'] = fan_modes_full.get(fan_num, "full auto")
            elif current_mode == "auto":
                fan_num = info[9]
                zone_status['auto_fan_mode_num'] = fan_num
                zone_status['auto_fan_mode'] = fan_modes_full.get(fan_num, "full auto")

            zone_data[zone_num] = zone_status

        hr_status['zones'] = zone_data
        hr_status['available_zones'] = sorted(available_zones)
        
        # For backward compatibility, if zone 0 exists, copy its data to the root level
        if 0 in zone_data:
            hr_status.update(zone_data[0])

        return hr_status

    @retry_bluetooth_connection_error(attempts=7)
    async def _connect_to_device(self, ble_device: BLEDevice):
        """Connect to the device with retries."""
        try:
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.address,
                timeout=20.0
            )
            if not self._client.services:
                await asyncio.sleep(2)
            if not self._client.services:
                _LOGGER.error("No services available after connecting")
                return False
            return self._client
        except Exception as e:
            _LOGGER.error("Connection error: %s", str(e))
            raise

    @retry_authentication(retries=3, delay=2)
    async def authenticate(self, password: str) -> bool:
        """Authenticate with the device using the provided password."""
        try:
            if not self._client or not self._client.is_connected:
                await asyncio.sleep(1)
                if not self._client or not self._client.is_connected:
                    await self._connect_to_device(self._ble_device)
                    await asyncio.sleep(0.5)
                if not self._client or not self._client.is_connected:
                    _LOGGER.error("Client not connected after reconnecting")
                    return False
            if not self._client.services:
                await self._client.discover_services()
                await asyncio.sleep(1)
                if not self._client.services:
                    _LOGGER.error("Services not discovered")
                    return False
            password_bytes = password.encode('utf-8')
            await self._client.write_gatt_char(UUIDS["passwordCmd"], password_bytes, response=True)
            _LOGGER.debug("Authentication sent successfully")
            return True
        except Exception as e:
            _LOGGER.error("Authentication failed: %s", str(e))
            if self._client and self._client.is_connected:
                await self._client.disconnect()
            self._client = None
            return False

    async def _write_gatt_with_retry(self, hass, uuid: str, data: bytes, ble_device: BLEDevice, retries: int = 3) -> bool:
        """Write GATT characteristic with retry and adaptive delay."""
        last_error = None
        for attempt in range(retries):
            try:
                if not self._client or not self._client.is_connected:
                    if not await self._reconnect_and_authenticate(hass, ble_device):
                        return False
                write_delay = self._get_operation_delay(hass, ble_device.address, 'write')
                if write_delay > 0:
                    await asyncio.sleep(write_delay)
                await self._client.write_gatt_char(uuid, data, response=True)
                self._adjust_operation_delay(hass, ble_device.address, 'write')
                return True
            except BleakError as e:
                last_error = e
                if attempt < retries - 1:
                    delay = self._increase_operation_delay(hass, ble_device.address, 'write')
                    _LOGGER.debug("GATT write failed, attempt %d/%d. Delay: %.1f", attempt + 1, retries, delay)
                    continue
        _LOGGER.error("GATT write failed after %d attempts: %s", retries, str(last_error))
        return False

    async def _reconnect_and_authenticate(self, hass, ble_device: BLEDevice) -> bool:
        """Reconnect and re-authenticate with adaptive delays."""
        try:
            connect_delay = self._get_operation_delay(hass, ble_device.address, 'connect')
            if connect_delay > 0:
                await asyncio.sleep(connect_delay)
            self._client = await self._connect_to_device(ble_device)
            if not self._client or not self._client.is_connected:
                self._increase_operation_delay(hass, ble_device.address, 'connect')
                return False
            self._adjust_operation_delay(hass, ble_device.address, 'connect')
            auth_delay = self._get_operation_delay(hass, ble_device.address, 'auth')
            if auth_delay > 0:
                await asyncio.sleep(auth_delay)
            auth_result = await self.authenticate(self._password)
            if auth_result:
                self._adjust_operation_delay(hass, ble_device.address, 'auth')
            else:
                self._increase_operation_delay(hass, ble_device.address, 'auth')
            return auth_result
        except Exception as e:
            _LOGGER.error("Reconnection failed: %s", str(e))
            self._increase_operation_delay(hass, ble_device.address, 'connect')
            return False

    async def _read_gatt_with_retry(self, hass, characteristic, ble_device: BLEDevice, retries: int = 3) -> bytes | None:
        """Read GATT characteristic with retry and operation-specific delay."""
        last_error = None
        for attempt in range(retries):
            try:
                if not self._client or not self._client.is_connected:
                    if not await self._reconnect_and_authenticate(hass, ble_device):
                        return None
                read_delay = self._get_operation_delay(hass, ble_device.address, 'read')
                if read_delay > 0:
                    await asyncio.sleep(read_delay)
                result = await self._client.read_gatt_char(characteristic)
                self._adjust_operation_delay(hass, ble_device.address, 'read')
                return result
            except BleakError as e:
                last_error = e
                if attempt < retries - 1:
                    delay = self._increase_operation_delay(hass, ble_device.address, 'read')
                    _LOGGER.debug("GATT read failed, attempt %d/%d. Delay: %.1f", attempt + 1, retries, delay)
                    continue
        _LOGGER.error("GATT read failed after %d attempts: %s", retries, str(last_error))
        return None

    async def reboot_device(self, hass, ble_device: BLEDevice) -> bool:
        """Reboot the device by sending reset command."""
        try:
            self._ble_device = ble_device
            self._client = await self._connect_to_device(ble_device)
            if not self._client or not self._client.is_connected:
                _LOGGER.error("Failed to connect for reboot")
                return False
            if not await self.authenticate(self._password):
                _LOGGER.error("Failed to authenticate for reboot")
                return False
            write_delay = self._get_operation_delay(hass, ble_device.address, 'write')
            if write_delay > 0:
                await asyncio.sleep(write_delay)
            reset_cmd = {"Type": "Change", "Changes": {"zone": 0, "reset": " OK"}}
            cmd_bytes = json.dumps(reset_cmd).encode()
            try:
                await self._client.write_gatt_char(UUIDS["jsonCmd"], cmd_bytes, response=True)
                _LOGGER.info("Reboot command sent successfully")
                return True
            except BleakError as e:
                if "Error" in str(e) and "133" in str(e):
                    _LOGGER.info("Device is rebooting as expected")
                    return True
                _LOGGER.error("Failed to send reboot command: %s", str(e))
                self._increase_operation_delay(hass, ble_device.address, 'write')
                return False
        except Exception as e:
            _LOGGER.error("Error during reboot: %s", str(e))
            return False
        finally:
            try:
                if self._client and self._client.is_connected:
                    await self._client.disconnect()
            except Exception as e:
                _LOGGER.debug("Error disconnecting after reboot: %s", str(e))
            self._client = None
            self._ble_device = None

    async def get_available_zones(self, hass, ble_device: BLEDevice) -> list[int]:
        """Get available zones from the device by querying its status."""
        try:
            message = {"Type": "Get Status", "Zone": 0, "EM": self._email, "TM": int(time.time())}
            if await self.send_command(hass, ble_device, message):
                json_payload = await self._read_gatt_with_retry(hass, UUIDS["jsonReturn"], ble_device)
                if json_payload:
                    decrypted_data = self.decrypt(json_payload.decode('utf-8'))
                    return decrypted_data.get('available_zones', [0])
            return [0]  # Default to zone 0 if detection fails
        except Exception as e:
            _LOGGER.error("Failed to get available zones: %s", str(e))
            return [0]  # Default to zone 0 if detection fails
            
    async def send_command(self, hass, ble_device: BLEDevice, command: dict) -> bool:
        """Send command to device."""
        try:
            if not self._client or not self._client.is_connected:
                self._client = await self._connect_to_device(ble_device)
                if not self._client or not self._client.is_connected:
                    return False
                if not await self.authenticate(self._password):
                    return False
            command_bytes = json.dumps(command).encode()
            return await self._write_gatt_with_retry(hass, UUIDS["jsonCmd"], command_bytes, ble_device)
        except Exception as e:
            _LOGGER.error("Error sending command: %s", str(e))
            return False
        finally:
            try:
                if self._client and self._client.is_connected:
                    await self._client.disconnect()
            except Exception as e:
                _LOGGER.debug("Error disconnecting: %s", str(e))
            self._client = None