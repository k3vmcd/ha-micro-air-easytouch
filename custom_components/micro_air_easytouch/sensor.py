"""Support for MicroAirEasyTouch temperature sensor."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity,
                                             SensorStateClass)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
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
    _attr_should_poll = False

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
        self._remove_callback: Callable[[], None] | None = None
        self._on_data_update: Callable[[], None] | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current ambient temperature from shared device state."""
        return self._data.current_state.get("facePlateTemperature")

    async def async_added_to_hass(self) -> None:
        """Register callback to update when climate platform fetches data."""

        def _on_data_update() -> None:
            self.async_write_ha_state()

        self._on_data_update = _on_data_update
        self._data.register_callback(self._on_data_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        if self._on_data_update is not None:
            self._data.unregister_callback(self._on_data_update)
            self._on_data_update = None
