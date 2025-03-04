"""Support for MicroAirEasyTouch climate control."""
from __future__ import annotations

import logging
import json
import time
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.bluetooth import async_ble_device_from_address

from .const import DOMAIN
from .micro_air_easytouch.parser import MicroAirEasyTouchBluetoothDeviceData
from .micro_air_easytouch.const import (
    UUIDS,
    HA_MODE_TO_EASY_MODE,
    EASY_MODE_TO_HA_MODE,
    FAN_MODES_FULL,
    FAN_MODES_FAN_ONLY,
    FAN_MODES_REVERSE,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MicroAirEasyTouch climate platform."""
    data = hass.data[DOMAIN][config_entry.entry_id]["data"]
    entity = MicroAirEasyTouchClimate(data, config_entry.unique_id)
    async_add_entities([entity])

class MicroAirEasyTouchClimate(ClimateEntity):
    """Representation of MicroAirEasyTouch Climate."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.FAN_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = list(HA_MODE_TO_EASY_MODE.keys())

    def __init__(self, data: MicroAirEasyTouchBluetoothDeviceData, mac_address: str) -> None:
        """Initialize the climate."""
        self._data = data
        self._mac_address = mac_address
        self._attr_unique_id = f"microaireasytouch_{mac_address}_climate"
        self._attr_name = "EasyTouch Climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"MicroAirEasyTouch_{mac_address}")},
            name=f"EasyTouch {mac_address}",
            manufacturer="Micro-Air",
            model="Thermostat",
        )
        self._state = {}

    async def _async_fetch_initial_state(self) -> None:
        """Fetch the initial state from the device."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device: %s", self._mac_address)
            self._state = {}
            return

        message = {"Type": "Get Status", "Zone": 0, "EM": self._data._email, "TM": int(time.time())}
        try:
            if await self._data.send_command(self.hass, ble_device, message):
                json_payload = await self._data._read_gatt_with_retry(self.hass, UUIDS["jsonReturn"], ble_device)
                if json_payload:
                    self._state = self._data.decrypt(json_payload.decode('utf-8'))
                    _LOGGER.debug("Initial state fetched: %s", self._state)
                    self.async_write_ha_state()
                else:
                    self._state = {}
                    _LOGGER.warning("No payload received for initial state")
            else:
                self._state = {}
                _LOGGER.warning("Failed to send command for initial state")
        except Exception as e:
            _LOGGER.error("Failed to fetch initial state: %s", str(e))
            self._state = {}

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._state.get("facePlateTemperature")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.hvac_mode == HVACMode.COOL:
            return self._state.get("cool_sp")
        elif self.hvac_mode == HVACMode.HEAT:
            return self._state.get("heat_sp")
        elif self.hvac_mode == HVACMode.DRY:
            return self._state.get("dry_sp")
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the high target temperature."""
        if self.hvac_mode == HVACMode.AUTO:
            return self._state.get("autoCool_sp")
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the low target temperature."""
        if self.hvac_mode == HVACMode.AUTO:
            return self._state.get("autoHeat_sp")
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation mode."""
        mode_num = self._state.get("mode_num", 0)
        return EASY_MODE_TO_HA_MODE.get(mode_num, HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action."""
        current_mode = self._state.get("current_mode")
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        elif current_mode == "fan":
            return HVACAction.FAN
        elif current_mode in ["cool", "cool_on"]:
            return HVACAction.COOLING
        elif current_mode in ["heat", "heat_on"]:
            return HVACAction.HEATING
        elif current_mode == "dry":
            return HVACAction.DRYING
        elif current_mode == "auto":
            # In auto mode, determine action based on temperature
            current_temp = self.current_temperature
            low = self.target_temperature_low
            high = self.target_temperature_high
            if current_temp is not None and low is not None and high is not None:
                if current_temp < low:
                    return HVACAction.HEATING
                elif current_temp > high:
                    return HVACAction.COOLING
            return HVACAction.IDLE
        return HVACAction.IDLE

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode based on HVAC mode."""
        if self.hvac_mode == HVACMode.FAN_ONLY:
            fan_mode_num = self._state.get("fan_mode_num", 0)
            return FAN_MODES_FAN_ONLY.get(fan_mode_num, "off")
        elif self.hvac_mode == HVACMode.COOL:
            return self._state.get("cool_fan_mode", "full auto")
        elif self.hvac_mode == HVACMode.HEAT:
            return self._state.get("heat_fan_mode", "full auto")
        elif self.hvac_mode == HVACMode.AUTO:
            return self._state.get("auto_fan_mode", "full auto")
        return "full auto"

    @property
    def fan_modes(self) -> list[str]:
        """Return available fan modes based on current HVAC mode."""
        if self.hvac_mode == HVACMode.FAN_ONLY:
            return list(FAN_MODES_FAN_ONLY.keys())
        return list(FAN_MODES_FULL.keys())

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device")
            return

        changes = {"zone": 0, "power": 1}
        if ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            if self.hvac_mode == HVACMode.COOL:
                changes["cool_sp"] = temp
            elif self.hvac_mode == HVACMode.HEAT:
                changes["heat_sp"] = temp
            elif self.hvac_mode == HVACMode.DRY:
                changes["dry_sp"] = temp
        elif "target_temp_high" in kwargs and "target_temp_low" in kwargs:
            changes["autoCool_sp"] = int(kwargs["target_temp_high"])
            changes["autoHeat_sp"] = int(kwargs["target_temp_low"])

        if changes:
            message = {"Type": "Change", "Changes": changes}
            await self._data.send_command(self.hass, ble_device, message)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
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
                    "mode": mode,
                },
            }
            await self._data.send_command(self.hass, ble_device, message)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device")
            return

        if self.hvac_mode == HVACMode.FAN_ONLY:
            fan_value = FAN_MODES_FAN_ONLY.get(fan_mode)
            if fan_value is not None:
                message = {"Type": "Change", "Changes": {"zone": 0, "fanOnly": fan_value}}
                await self._data.send_command(self.hass, ble_device, message)
        else:
            fan_value = FAN_MODES_FULL.get(fan_mode)
            if fan_value is not None:
                changes = {"zone": 0}
                if self.hvac_mode == HVACMode.COOL:
                    changes["coolFan"] = fan_value
                elif self.hvac_mode == HVACMode.HEAT:
                    changes["heatFan"] = fan_value
                elif self.hvac_mode == HVACMode.AUTO:
                    changes["autoFan"] = fan_value
                message = {"Type": "Change", "Changes": changes}
                await self._data.send_command(self.hass, ble_device, message)

    async def async_update(self) -> None:
        """Update the entity state manually if needed."""
        await self._async_fetch_initial_state()