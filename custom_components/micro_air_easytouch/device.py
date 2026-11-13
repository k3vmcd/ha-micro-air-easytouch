"""Helpers for EasyTouch device transports."""

from __future__ import annotations

from homeassistant.components.bluetooth import async_ble_device_from_address


def is_cloud_data(data) -> bool:
    """Return whether a device data object uses the cloud transport."""
    return getattr(data, "is_cloud", False)


def ble_device_for_data(hass, data, address: str):
    """Return a BLE device when needed, or None for cloud devices."""
    if is_cloud_data(data):
        return None
    return async_ble_device_from_address(
        hass, getattr(data, "transport_address", address)
    )
