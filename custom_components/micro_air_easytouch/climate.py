"""Support for MicroAirEasyTouch climate control."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_LOW,
    FAN_HIGH,
    FAN_OFF,
    ATTR_TARGET_TEMP_LOW,
    ATTR_TARGET_TEMP_HIGH,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.bluetooth import async_ble_device_from_address

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Map EasyTouch modes to Home Assistant modes
HA_MODE_TO_EASY_MODE = {
    HVACMode.OFF: 0,
    HVACMode.FAN_ONLY: 1,
    HVACMode.COOL: 2,
    HVACMode.HEAT: 4,
    HVACMode.AUTO: 11,
}

EASY_MODE_TO_HA_MODE = {v: k for k, v in HA_MODE_TO_EASY_MODE.items()}

FAN_MODES = {
    FAN_OFF: 0,
    FAN_LOW: 1,
    FAN_HIGH: 2,
    FAN_AUTO: 128,
}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MicroAirEasyTouch climate platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    data = hass.data[DOMAIN][config_entry.entry_id]["data"]
    
    async_add_entities([MicroAirEasyTouchClimate(coordinator, data)])

class MicroAirEasyTouchClimate(ClimateEntity):
    """Representation of MicroAirEasyTouch Climate."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE 
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.FAN_MODE
    )
    
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.AUTO,
        HVACMode.FAN_ONLY,
    ]
    _attr_fan_modes = list(FAN_MODES.keys())
    
    def __init__(self, coordinator, data) -> None:
        """Initialize the climate."""
        self.coordinator = coordinator
        self._data = data
        self._attr_has_entity_name = True
        
        # Set unique_id using the MAC address
        mac_address = coordinator.name.split('_')[-1]
        self._attr_unique_id = f"microaireasytouch_{mac_address}_climate"
        self._attr_name = "EasyTouch Climate"
        
        # Set device info
        device_name = f"EasyTouch {mac_address}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.name)},
            name=device_name,
            manufacturer="Micro-Air",
            model="Thermostat",
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.coordinator.data:
            temp = next(
                (
                    value
                    for key, value in self.coordinator.data.entity_data.items()
                    if key.key == "face_plate_temperature"
                ),
                None,
            )
            return temp
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.coordinator.data and self.hvac_mode == HVACMode.COOL:
            temp = next(
                (
                    value
                    for key, value in self.coordinator.data.entity_data.items()
                    if key.key == "cool_sp"
                ),
                None,
            )
            return temp
        elif self.coordinator.data and self.hvac_mode == HVACMode.HEAT:
            temp = next(
                (
                    value
                    for key, value in self.coordinator.data.entity_data.items()
                    if key.key == "heat_sp"
                ),
                None,
            )
            return temp
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the high target temperature."""
        if self.coordinator.data and self.hvac_mode == HVACMode.AUTO:
            return next(
                (
                    value
                    for key, value in self.coordinator.data.entity_data.items()
                    if key.key == "autoCool_sp"
                ),
                None,
            )
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the low target temperature."""
        if self.coordinator.data and self.hvac_mode == HVACMode.AUTO:
            return next(
                (
                    value
                    for key, value in self.coordinator.data.entity_data.items()
                    if key.key == "autoHeat_sp"
                ),
                None,
            )
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation mode."""
        if self.coordinator.data:
            mode = next(
                (
                    value
                    for key, value in self.coordinator.data.entity_data.items()
                    if key.key == "mode"
                ),
                None,
            )
            if mode == "off":
                return HVACMode.OFF
            elif mode == "fan":
                return HVACMode.FAN_ONLY
            elif mode in ["cool", "cool_on"]:
                return HVACMode.COOL
            elif mode in ["heat", "heat_on"]:
                return HVACMode.HEAT
            elif mode == "auto":
                return HVACMode.AUTO
        return HVACMode.OFF

    @property
    def fan_mode(self) -> str:
        """Return the fan setting."""
        if self.coordinator.data:
            mode = next(
                (
                    value
                    for key, value in self.coordinator.data.entity_data.items()
                    if key.key == "fan_mode"
                ),
                None,
            )
            if mode == "off":
                return FAN_OFF
            elif mode == "manualL":
                return FAN_LOW
            elif mode == "manualH":
                return FAN_HIGH
            elif mode == "full auto":
                return FAN_AUTO
        return FAN_AUTO

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        ble_device = async_ble_device_from_address(self.coordinator.hass, self.coordinator.name.split('_')[-1])
        if not ble_device:
            _LOGGER.error("Could not find BLE device")
            return
            
        changes = {"zone": 0, "power": 1}

        if ATTR_TEMPERATURE in kwargs and self.hvac_mode in [HVACMode.COOL, HVACMode.HEAT]:
            temp = int(kwargs[ATTR_TEMPERATURE])
            if self.hvac_mode == HVACMode.COOL:
                changes["cool_sp"] = temp
            else:
                changes["heat_sp"] = temp
                
        elif all(x in kwargs for x in (ATTR_TARGET_TEMP_HIGH, ATTR_TARGET_TEMP_LOW)):
            changes["autoCool_sp"] = int(kwargs[ATTR_TARGET_TEMP_HIGH])
            changes["autoHeat_sp"] = int(kwargs[ATTR_TARGET_TEMP_LOW])

        if changes:
            message = {"Type": "Change", "Changes": changes}
            await self._data.send_command(self.coordinator.hass, ble_device, message)
            await self.coordinator.async_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        ble_device = async_ble_device_from_address(self.coordinator.hass, self.coordinator.name.split('_')[-1])
        if not ble_device:
            _LOGGER.error("Could not find BLE device")
            return
            
        mode = HA_MODE_TO_EASY_MODE.get(hvac_mode)
        if mode is not None:
            message = {
                "Type": "Change",
                "Changes": {
                    "zone": 0,
                    "power": 0 if hvac_mode == HVACMode.OFF else 1,
                    "mode": mode
                }
            }
            await self._data.send_command(self.coordinator.hass, ble_device, message)
            await self.coordinator.async_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        ble_device = async_ble_device_from_address(self.coordinator.hass, self.coordinator.name.split('_')[-1])
        if not ble_device:
            _LOGGER.error("Could not find BLE device")
            return
            
        fan_value = FAN_MODES.get(fan_mode)
        if fan_value is not None:
            message = {
                "Type": "Change", 
                "Changes": {
                    "zone": 0,
                    "fanOnly": fan_value
                }
            }
            await self._data.send_command(self.coordinator.hass, ble_device, message)
            await self.coordinator.async_refresh()