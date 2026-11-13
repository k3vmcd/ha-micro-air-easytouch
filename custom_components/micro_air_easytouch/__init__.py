"""MicroAirEasyTouch Integration"""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_CONTROL_TYPE,
    CONN_TYPE_BLE,
    DOMAIN,
)
from .micro_air_easytouch.cloud import MicroAirEasyTouchCloudDeviceData
from .micro_air_easytouch.parser import MicroAirEasyTouchBluetoothDeviceData
from .services import async_register_services, async_unregister_services

PLATFORMS: Final = [Platform.BUTTON, Platform.CLIMATE, Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MicroAirEasyTouch from a config entry."""
    address = entry.unique_id
    assert address is not None
    password = entry.data.get(CONF_PASSWORD)
    email = entry.data.get(CONF_USERNAME)
    connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONN_TYPE_BLE)

    if connection_type == CONN_TYPE_BLE:
        data = MicroAirEasyTouchBluetoothDeviceData(password=password, email=email)
    else:
        data = MicroAirEasyTouchCloudDeviceData(
            password=password,
            email=email,
            serial_number=entry.data[CONF_ADDRESS],
            control_type=entry.data.get(CONF_CONTROL_TYPE, "EasyTouch"),
        )

    data.transport_address = entry.data.get(CONF_ADDRESS, address)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"data": data}

    if isinstance(data, MicroAirEasyTouchCloudDeviceData):
        try:
            await data.async_start(hass)
        except Exception as exc:
            await data.async_stop()
            hass.data[DOMAIN].pop(entry.entry_id)
            raise ConfigEntryNotReady(
                f"Could not connect to Micro-Air cloud: {type(exc).__name__}"
            ) from exc
    else:

        @callback
        def _handle_bluetooth_update(service_info: BluetoothServiceInfoBleak) -> None:
            """Update device info from advertisements."""
            if service_info.address == data.transport_address:
                _LOGGER.debug(
                    "Received BLE advertisement from %s: %s",
                    data.transport_address,
                    service_info,
                )
                data._start_update(service_info)

        hass.bus.async_listen("bluetooth_service_info", _handle_bluetooth_update)

    await async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN][entry.entry_id]["data"]
        if isinstance(data, MicroAirEasyTouchCloudDeviceData):
            await data.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id)
        await async_unregister_services(hass)
    return unload_ok
