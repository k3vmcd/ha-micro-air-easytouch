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
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import RestoreEntity

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

class MicroAirEasyTouchClimate(ClimateEntity, RestoreEntity):
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
        self._last_known_hvac_mode: HVACMode | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known active mode on startup so we don't flash 'Off'."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN, None):
            try:
                restored_mode = HVACMode(last_state.state)
                if restored_mode != HVACMode.OFF:
                    self._last_known_hvac_mode = restored_mode
                    _LOGGER.debug("Restored last known hvac mode: %s", restored_mode)
            except (ValueError, KeyError):
                pass

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

    async def _async_fetch_state(self) -> None:
        """Fetch the current state from the device."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device: %s", self._mac_address)
            return

        message = {"Type": "Get Status", "Zone": 0, "EM": self._data._email, "TM": int(time.time())}
        try:
            if await self._data.send_command(self.hass, ble_device, message):
                json_payload = await self._data._read_gatt_with_retry(self.hass, UUIDS["jsonReturn"], ble_device)
                if json_payload:
                    new_state = self._data.decrypt(json_payload.decode('utf-8'))
                    # Preserve existing state if fetch returns empty/partial data
                    if new_state:
                        self._state = new_state
                        # Track last active mode so transient OFF readings don't
                        # lose the real state (used as fallback in hvac_mode).
                        mode_num = new_state.get("current_mode_num")
                        if mode_num is not None and mode_num != 0:
                            self._last_known_hvac_mode = EASY_MODE_TO_HA_MODE.get(
                                mode_num, self._last_known_hvac_mode
                            )
                        _LOGGER.debug("State fetched: %s", self._state)
                        self.async_write_ha_state()
                else:
                    _LOGGER.warning("No payload received for state fetch")
            else:
                _LOGGER.warning("Failed to send command for state fetch")
        except Exception as e:
            _LOGGER.error("Failed to fetch state: %s", str(e))

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
        # PRM flags are the authoritative power state: 7=off, 15=on.
        # Check them first so a device reporting ON in PRM but mode=0 in
        # current_mode_num (transitional state) is not shown as OFF.
        if self._state.get("off") and not self._state.get("on"):
            return HVACMode.OFF
        current_mode_num = self._state.get("current_mode_num")
        if current_mode_num == 0 and self._state.get("off"):
            return HVACMode.OFF
        if current_mode_num is not None:
            return EASY_MODE_TO_HA_MODE.get(current_mode_num, HVACMode.OFF)
        # No state yet (before first poll) — return last known active mode.
        if self._last_known_hvac_mode is not None:
            return self._last_known_hvac_mode
        return HVACMode.OFF

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
            raise HomeAssistantError("Could not find BLE device")

        changes = {}
        if ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            if self.hvac_mode == HVACMode.COOL:
                changes["cool_sp"] = temp
                self._state["cool_sp"] = temp
            elif self.hvac_mode == HVACMode.HEAT:
                changes["heat_sp"] = temp
                self._state["heat_sp"] = temp
            elif self.hvac_mode == HVACMode.DRY:
                changes["dry_sp"] = temp
                self._state["dry_sp"] = temp
        elif "target_temp_high" in kwargs and "target_temp_low" in kwargs:
            changes["autoCool_sp"] = int(kwargs["target_temp_high"])
            changes["autoHeat_sp"] = int(kwargs["target_temp_low"])
            self._state["autoCool_sp"] = int(kwargs["target_temp_high"])
            self._state["autoHeat_sp"] = int(kwargs["target_temp_low"])

        if not changes:
            return

        # Add required fields only when we have actual temperature changes
        changes["zone"] = 0
        changes["power"] = 1

        # Optimistic update - show new state immediately
        self.async_write_ha_state()

        message = {"Type": "Change", "Changes": changes}
        try:
            if not await self._data.send_command(self.hass, ble_device, message):
                raise HomeAssistantError("Failed to set temperature")
        finally:
            # Always refresh state from device to correct optimistic update
            await self._async_fetch_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            raise HomeAssistantError("Could not find BLE device")

        mode = HA_MODE_TO_EASY_MODE.get(hvac_mode)
        if mode is not None:
            # Optimistic update — write to the keys hvac_mode actually reads
            self._state["current_mode_num"] = mode
            if hvac_mode == HVACMode.OFF:
                self._state["off"] = True
                self._state.pop("on", None)
            else:
                self._state["on"] = True
                self._state.pop("off", None)
            self.async_write_ha_state()
            
            message = {
                "Type": "Change",
                "Changes": {
                    "zone": 0,
                    "power": 0 if hvac_mode == HVACMode.OFF else 1,
                    "mode": mode,
                },
            }
            try:
                if not await self._data.send_command(self.hass, ble_device, message):
                    raise HomeAssistantError(f"Failed to set HVAC mode to {hvac_mode}")
            finally:
                # Always refresh state from device to correct optimistic update
                await self._async_fetch_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode using standard Home Assistant names."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            raise HomeAssistantError("Could not find BLE device")

        # Map standard name to device value and build changes
        if self.hvac_mode == HVACMode.FAN_ONLY:
            if fan_mode == "off":
                fan_value = 0
            elif fan_mode == "low":
                fan_value = 1
            elif fan_mode == "high":
                fan_value = 2
            else:
                fan_value = 0
            changes = {"zone": 0, "fanOnly": fan_value}
            self._state["fan_mode_num"] = fan_value
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
            changes = {}
            if self.hvac_mode == HVACMode.COOL:
                changes["coolFan"] = fan_value
                self._state["cool_fan_mode_num"] = fan_value
            elif self.hvac_mode == HVACMode.HEAT:
                changes["heatFan"] = fan_value
                self._state["heat_fan_mode_num"] = fan_value
            elif self.hvac_mode == HVACMode.AUTO:
                changes["autoFan"] = fan_value
                self._state["auto_fan_mode_num"] = fan_value

            if not changes:
                # OFF or DRY mode - no fan key to set, skip BLE round-trip
                return

            changes["zone"] = 0

        self.async_write_ha_state()

        message = {"Type": "Change", "Changes": changes}
        try:
            if not await self._data.send_command(self.hass, ble_device, message):
                raise HomeAssistantError(f"Failed to set fan mode to {fan_mode}")
        finally:
            # Always refresh state from device to correct optimistic update
            await self._async_fetch_state()

    async def async_update(self) -> None:
        """Update the entity state from device."""
        await self._async_fetch_state()