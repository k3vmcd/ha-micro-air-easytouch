"""Service handlers for MicroAirEasyTouch integration."""

from __future__ import annotations

import logging
import time

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .device import ble_device_for_data, is_cloud_data

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_LOCATION_SCHEMA = vol.Schema(
    {
        vol.Optional("address"): cv.string,
        vol.Required("latitude"): vol.All(
            vol.Coerce(float), vol.Range(min=-90.0, max=90.0)
        ),
        vol.Required("longitude"): vol.All(
            vol.Coerce(float), vol.Range(min=-180.0, max=180.0)
        ),
    }
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register services for the MicroAirEasyTouch integration."""

    async def handle_set_location(call: ServiceCall) -> None:
        """Set thermostat coordinates, inferring a sole configured device."""
        address = call.data.get("address")
        latitude = call.data["latitude"]
        longitude = call.data["longitude"]
        entries = hass.config_entries.async_entries(DOMAIN)

        if address:
            config_entry = next(
                (
                    entry
                    for entry in entries
                    if address in (entry.unique_id, entry.data.get(CONF_ADDRESS))
                ),
                None,
            )
        elif len(entries) == 1:
            config_entry = entries[0]
        else:
            raise HomeAssistantError(
                "The address field is required when multiple EasyTouch thermostats "
                "are configured"
            )

        if config_entry is None:
            raise HomeAssistantError(
                f"No MicroAirEasyTouch config entry found for {address or 'the requested device'}"
            )

        device_data = hass.data[DOMAIN][config_entry.entry_id]["data"]
        device_address = config_entry.data.get(CONF_ADDRESS, config_entry.unique_id)
        ble_device = ble_device_for_data(hass, device_data, device_address)
        if not ble_device and not is_cloud_data(device_data):
            raise HomeAssistantError(
                f"Could not find BLE device for address {device_address}"
            )

        command = {
            "Type": "Get Status",
            "Zone": 0,
            "LAT": f"{latitude:.5f}",
            "LON": f"{longitude:.5f}",
            "TM": int(time.time()),
        }
        success = await device_data.send_command(hass, ble_device, command)
        if not success:
            raise HomeAssistantError(
                f"Failed to send location command to device {device_address}"
            )
        _LOGGER.info(
            "Successfully sent location to EasyTouch device %s", device_address
        )

    hass.services.async_register(
        DOMAIN,
        "set_location",
        handle_set_location,
        schema=SERVICE_SET_LOCATION_SCHEMA,
    )


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services for the MicroAirEasyTouch integration."""
    hass.services.async_remove(DOMAIN, "set_location")
