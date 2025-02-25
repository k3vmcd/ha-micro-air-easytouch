"""Support for MicroAirEasyTouch buttons."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.bluetooth import async_ble_device_from_address

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MicroAirEasyTouch button based on a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    data = hass.data[DOMAIN][config_entry.entry_id]["data"]
    
    async_add_entities([MicroAirEasyTouchRebootButton(coordinator, data)])

class MicroAirEasyTouchRebootButton(ButtonEntity):
    """Representation of a reboot button for MicroAirEasyTouch."""

    def __init__(self, coordinator, data) -> None:
        """Initialize the button."""
        self.coordinator = coordinator
        self._data = data
        
        # Set unique_id using the MAC address
        self._mac_address = coordinator.name.split('_')[-1]
        self._attr_unique_id = f"microaireasytouch_{self._mac_address}_reboot"
        self._attr_name = "Reboot Device"
        
        # Set device info
        device_name = f"EasyTouch {self._mac_address}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.name)},
            name=device_name,
            manufacturer="Micro-Air",
            model="Thermostat",
        )
        
    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.debug("Reboot button pressed")
        # Get BLE device from address
        ble_device = async_ble_device_from_address(self.coordinator.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device for reboot: %s", self._mac_address)
            return
        await self._data.reboot_device(self.coordinator.hass, ble_device)