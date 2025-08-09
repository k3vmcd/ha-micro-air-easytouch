"""Service handlers for MicroAirEasyTouch integration."""
from __future__ import annotations

import logging
import time
import voluptuous as vol

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .micro_air_easytouch.parser import MicroAirEasyTouchBluetoothDeviceData

_LOGGER = logging.getLogger(__name__)

# Service schema for validation
SERVICE_SET_LOCATION_SCHEMA = vol.Schema(
    {
        vol.Required("address"): cv.string,
        vol.Required("latitude"): vol.All(vol.Coerce(float), vol.Range(min=-90.0, max=90.0)),
        vol.Required("longitude"): vol.All(vol.Coerce(float), vol.Range(min=-180.0, max=180.0)),
    }
)

async def async_register_services(hass: HomeAssistant) -> None:
    """Register services for the MicroAirEasyTouch integration."""
    async def handle_set_location(call: ServiceCall) -> None:
        """Handle the set_location service call."""
        address = call.data.get("address")
        latitude = call.data.get("latitude")
        longitude = call.data.get("longitude")

        # Find the config entry by MAC address (unique_id)
        config_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.unique_id == address:
                config_entry = entry
                break

        if not config_entry:
            _LOGGER.error("No MicroAirEasyTouch config entry found for address %s", address)
            return

        # Get the device data
        device_data: MicroAirEasyTouchBluetoothDeviceData = hass.data[DOMAIN][config_entry.entry_id]["data"]
        mac_address = config_entry.unique_id
        assert mac_address is not None

        # Get BLE device
        ble_device = async_ble_device_from_address(hass, mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device for address %s", mac_address)
            return

        # Construct the command
        command = {
            "Type": "Get Status",
            "Zone": 0,  # Location setting is global, not zone-specific
            "LAT": f"{latitude:.5f}",
            "LON": f"{longitude:.5f}",
            "TM": int(time.time())
        }

        # Send the command
        try:
            success = await device_data.send_command(hass, ble_device, command)
            if success:
                _LOGGER.info("Successfully sent location (LAT: %s, LON: %s) to device %s", latitude, longitude, mac_address)
            else:
                _LOGGER.error("Failed to send location command to device %s", mac_address)
        except Exception as e:
            _LOGGER.error("Error sending location command to device %s: %s", mac_address, str(e))

    # Register the service
    hass.services.async_register(
        DOMAIN,
        "set_location",
        handle_set_location,
        schema=SERVICE_SET_LOCATION_SCHEMA,
    )

async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services for the MicroAirEasyTouch integration."""
    hass.services.async_remove(DOMAIN, "set_location")