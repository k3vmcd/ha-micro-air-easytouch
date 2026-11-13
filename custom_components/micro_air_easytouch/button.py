"""Support for MicroAirEasyTouch buttons."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import ble_device_for_data, is_cloud_data
from .micro_air_easytouch.parser import MicroAirEasyTouchBluetoothDeviceData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MicroAirEasyTouch button based on a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]["data"]
    mac_address = config_entry.unique_id
    assert mac_address is not None
    async_add_entities([MicroAirEasyTouchRebootButton(data, mac_address)])


class MicroAirEasyTouchRebootButton(ButtonEntity):
    """Representation of a reboot button for MicroAirEasyTouch."""

    def __init__(
        self, data: MicroAirEasyTouchBluetoothDeviceData, mac_address: str
    ) -> None:
        """Initialize the button."""
        self._data = data
        self._mac_address = mac_address
        self._attr_unique_id = f"microaireasytouch_{self._mac_address}_reboot"
        self._attr_name = "Reboot Device"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"MicroAirEasyTouch_{self._mac_address}")},
            name=f"EasyTouch {self._mac_address}",
            manufacturer="Micro-Air",
            model="Thermostat",
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.debug("Reboot button pressed")
        ble_device = ble_device_for_data(self.hass, self._data, self._mac_address)
        if not ble_device and not is_cloud_data(self._data):
            _LOGGER.error("Could not find BLE device for reboot: %s", self._mac_address)
            return
        await self._data.reboot_device(self.hass, ble_device)
