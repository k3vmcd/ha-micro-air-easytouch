"""MicroAirEasyTouch Integration"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Final

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback

from .MicroAirEasyTouch import MicroAirEasyTouchBluetoothDeviceData, SensorUpdate
from .MicroAirEasyTouch.const import UPDATE_INTERVAL
from .const import DOMAIN
from .sensor import sensor_update_to_bluetooth_data_update

PLATFORMS: Final = [Platform.SENSOR]
# PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MicroAirEasyTouch from a config entry."""
    address = entry.unique_id
    assert address is not None
    password = entry.data.get(CONF_PASSWORD)
    email = entry.data.get(CONF_USERNAME)
    data = MicroAirEasyTouchBluetoothDeviceData(password=password, email=email)

# DataUpdateCoordinator for periodic polling
    async def _async_update_data():
        """Fetch data from the device."""
        ble_device = async_ble_device_from_address(hass, address)
        if not ble_device:
            _LOGGER.debug("No BLE device found for address %s, skipping poll", address)
            return None
        try:
            update = await data.async_poll(ble_device)
            return sensor_update_to_bluetooth_data_update(update)
        except Exception as e:
            _LOGGER.error("Failed to poll device: %s", e)
            raise

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"MicroAirEasyTouch_{address}",
        update_method=_async_update_data,
        update_interval=timedelta(seconds=UPDATE_INTERVAL),
    )

    # Store coordinator in hass.data
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "data": data,
    }

    # Handle initial device info from advertisements
    @callback
    def _handle_bluetooth_update(service_info: BluetoothServiceInfoBleak) -> SensorUpdate:
        """Update device info from advertisements and trigger a refresh."""
        if service_info.address == address:
            data._start_update(service_info)  # Set device name dynamically
            coordinator.async_set_updated_data(None)  # Trigger initial poll if needed

    hass.bus.async_listen("bluetooth_service_info", _handle_bluetooth_update)

    _LOGGER.debug("Starting coordinator for %s", address)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_config_entry_first_refresh()  # Start polling

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok