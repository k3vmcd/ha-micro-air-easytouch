"""Support for MicroAirEasyTouch temperature sensor."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity,
                                             SensorStateClass)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .micro_air_easytouch.const import UUIDS
from .micro_air_easytouch.parser import MicroAirEasyTouchBluetoothDeviceData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MicroAirEasyTouch sensor platform."""
    data: MicroAirEasyTouchBluetoothDeviceData = hass.data[DOMAIN][
        config_entry.entry_id
    ]["data"]
    mac_address = config_entry.unique_id
    assert mac_address is not None
    async_add_entities([MicroAirEasyTouchTemperatureSensor(data, mac_address)])


class MicroAirEasyTouchTemperatureSensor(SensorEntity):
    """Representation of the MicroAirEasyTouch ambient temperature sensor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_should_poll = True

    def __init__(
        self,
        data: MicroAirEasyTouchBluetoothDeviceData,
        mac_address: str,
    ) -> None:
        """Initialize the temperature sensor."""
        self._data = data
        self._mac_address = mac_address
        self._attr_unique_id = f"microaireasytouch_{mac_address}_current_temperature"
        self._attr_name = "Current Temperature"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"MicroAirEasyTouch_{mac_address}")},
            name=f"EasyTouch {mac_address}",
            manufacturer="Micro-Air",
            model="Thermostat",
        )
        self._state: dict[str, Any] = {}

    @property
    def native_value(self) -> float | None:
        """Return the current ambient temperature."""
        return self._state.get("facePlateTemperature")

    async def _async_fetch_state(self) -> None:
        """Fetch the current state from the device."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device: %s", self._mac_address)
            self._state = {}
            return

        message = {
            "Type": "Get Status",
            "Zone": 0,
            "EM": self._data._email,
            "TM": int(time.time()),
        }
        try:
            if await self._data.send_command(self.hass, ble_device, message):
                json_payload = await self._data._read_gatt_with_retry(
                    self.hass, UUIDS["jsonReturn"], ble_device
                )
                if json_payload:
                    self._state = self._data.decrypt(json_payload.decode("utf-8"))
                    _LOGGER.debug("Temperature sensor state fetched: %s", self._state)
                else:
                    self._state = {}
                    _LOGGER.warning("No payload received for temperature sensor")
            else:
                self._state = {}
                _LOGGER.warning("Failed to send command for temperature sensor")
        except Exception as e:
            _LOGGER.error("Failed to fetch temperature sensor state: %s", str(e))
            self._state = {}

    async def async_update(self) -> None:
        """Update the sensor state."""
        await self._async_fetch_state()
