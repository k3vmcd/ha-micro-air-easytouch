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
    mac_address = config_entry.unique_id
    
    # Get BLE device to probe for available zones
    ble_device = async_ble_device_from_address(hass, mac_address)
    if not ble_device:
        _LOGGER.error("Could not find BLE device to detect zones: %s", mac_address)
        # Fall back to single zone if device not found
        entity = MicroAirEasyTouchClimate(data, mac_address, 0)
        async_add_entities([entity])
        return
    
    # Probe device for available zones
    try:
        available_zones = await data.get_available_zones(hass, ble_device)
        _LOGGER.info("Detected zones for device %s: %s", mac_address, available_zones)
        
        entities = []
        for zone in available_zones:
            entity = MicroAirEasyTouchClimate(data, mac_address, zone)
            entities.append(entity)
        
        async_add_entities(entities)
    except Exception as e:
        _LOGGER.error("Failed to detect zones for device %s: %s", mac_address, str(e))
        # Fall back to single zone if detection fails
        entity = MicroAirEasyTouchClimate(data, mac_address, 0)
        async_add_entities([entity])

class MicroAirEasyTouchClimate(ClimateEntity):
    """Representation of MicroAirEasyTouch Climate."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.FAN_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = list(HA_MODE_TO_EASY_MODE.keys())
    _attr_should_poll = True

    # Map our modes to Home Assistant fan icons
    _FAN_MODE_ICONS = {
        "off": "mdi:fan-off",
        "low": "mdi:fan-speed-1",
        "high": "mdi:fan-speed-3",
        "manualL": "mdi:fan-speed-1",
        "manualH": "mdi:fan-speed-3",
        "cycledL": "mdi:fan-clock",
        "cycledH": "mdi:fan-clock",
        "full auto": "mdi:fan-auto",
    }

    # Map HVAC modes to icons
    _HVAC_MODE_ICONS = {
        HVACMode.OFF: "mdi:power",
        HVACMode.HEAT: "mdi:fire",
        HVACMode.COOL: "mdi:snowflake",
        HVACMode.AUTO: "mdi:autorenew",
        HVACMode.FAN_ONLY: "mdi:fan",
        HVACMode.DRY: "mdi:water-percent",
    }

    # Map device fan modes to Home Assistant standard names
    _FAN_MODE_MAP = {
        "off": "off",
        "low": "low",
        "manualL": "low",
        "cycledL": "low",
        "high": "high",
        "manualH": "high",
        "cycledH": "high",
        "full auto": "auto",
    }
    _FAN_MODE_REVERSE_MAP = {
        "off": [0],
        "low": [1, 65],
        "high": [2, 66],
        "auto": [128],
    }

    def __init__(self, data: MicroAirEasyTouchBluetoothDeviceData, mac_address: str, zone: int) -> None:
        """Initialize the climate."""
        self._data = data
        self._mac_address = mac_address
        self._zone = zone
        self._attr_unique_id = f"microaireasytouch_{mac_address}_climate_zone_{zone}"
        self._attr_name = f"EasyTouch Climate Zone {zone}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"MicroAirEasyTouch_{mac_address}")},
            name=f"EasyTouch {mac_address}",
            manufacturer="Micro-Air",
            model="Thermostat",
        )
        self._state = {}

    @property
    def icon(self) -> str:
        """Return the entity icon."""
        return self._HVAC_MODE_ICONS.get(self.hvac_mode, "mdi:thermostat")

    @property
    def entity_picture(self) -> str | None:
        """Return the entity picture."""
        if self.fan_mode:
            return f"mdi:{self._FAN_MODE_ICONS.get(self.fan_mode, 'fan')}"
        return None

    @property
    def current_fan_icon(self) -> str:
        """Return the icon to use for the current fan mode."""
        return self._FAN_MODE_ICONS.get(self.fan_mode, "mdi:fan")

    async def _async_fetch_initial_state(self) -> None:
        """Fetch the initial state from the device."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device: %s", self._mac_address)
            self._state = {}
            return

        message = {"Type": "Get Status", "Zone": self._zone, "EM": self._data._email, "TM": int(time.time())}
        try:
            if await self._data.send_command(self.hass, ble_device, message):
                json_payload = await self._data._read_gatt_with_retry(self.hass, UUIDS["jsonReturn"], ble_device)
                if json_payload:
                    full_data = self._data.decrypt(json_payload.decode('utf-8'))
                    # Get zone-specific data
                    if 'zones' in full_data and self._zone in full_data['zones']:
                        self._state = full_data['zones'][self._zone]
                    else:
                        # Fall back to root level data if zones not available (backward compatibility)
                        self._state = full_data
                    _LOGGER.debug("Initial state fetched for zone %s: %s", self._zone, self._state)
                    self.async_write_ha_state()
                else:
                    self._state = {}
                    _LOGGER.warning("No payload received for initial state zone %s", self._zone)
            else:
                self._state = {}
                _LOGGER.warning("Failed to send command for initial state zone %s", self._zone)
        except Exception as e:
            _LOGGER.error("Failed to fetch initial state for zone %s: %s", self._zone, str(e))
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
        """Return the current fan mode as a standard Home Assistant name."""
        if self.hvac_mode == HVACMode.FAN_ONLY:
            fan_mode_num = self._state.get("fan_mode_num", 0)
            mode = FAN_MODES_FAN_ONLY.get(fan_mode_num, "off")
        elif self.hvac_mode == HVACMode.COOL:
            fan_mode_num = self._state.get("cool_fan_mode_num", 128)
            mode = FAN_MODES_REVERSE.get(fan_mode_num, "full auto")
        elif self.hvac_mode == HVACMode.HEAT:
            fan_mode_num = self._state.get("heat_fan_mode_num", 128)
            mode = FAN_MODES_REVERSE.get(fan_mode_num, "full auto")
        elif self.hvac_mode == HVACMode.AUTO:
            fan_mode_num = self._state.get("auto_fan_mode_num", 128)
            mode = FAN_MODES_REVERSE.get(fan_mode_num, "full auto")
        else:
            mode = "full auto"
        return self._FAN_MODE_MAP.get(mode, "auto")

    @property
    def fan_modes(self) -> list[str]:
        """Return available fan modes as standard Home Assistant names."""
        if self.hvac_mode == HVACMode.FAN_ONLY:
            return ["off", "low", "high"]
        return ["off", "low", "high", "auto"]

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device")
            return

        changes = {"zone": self._zone, "power": 1}
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
                    "zone": self._zone,
                    "power": 0 if hvac_mode == HVACMode.OFF else 1,
                    "mode": mode,
                },
            }
            await self._data.send_command(self.hass, ble_device, message)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode using standard Home Assistant names."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device")
            return

        # Map standard name to device value
        if self.hvac_mode == HVACMode.FAN_ONLY:
            if fan_mode == "off":
                fan_value = 0
            elif fan_mode == "low":
                fan_value = 1
            elif fan_mode == "high":
                fan_value = 2
            else:
                fan_value = 0
            message = {"Type": "Change", "Changes": {"zone": self._zone, "fanOnly": fan_value}}
            await self._data.send_command(self.hass, ble_device, message)
        else:
            if fan_mode == "off":
                fan_value = 0
            elif fan_mode == "low":
                fan_value = 1  # manualL
            elif fan_mode == "high":
                fan_value = 2  # manualH
            elif fan_mode == "auto":
                fan_value = 128  # full auto
            else:
                fan_value = 128
            changes = {"zone": self._zone}
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