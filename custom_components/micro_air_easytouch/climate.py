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
from .micro_air_easytouch.parser import MicroAirEasyTouchBluetoothDeviceData  # Corrected import
from .micro_air_easytouch.const import UUIDS

_LOGGER = logging.getLogger(__name__)

# Map EasyTouch modes to Home Assistant modes
HA_MODE_TO_EASY_MODE = {
    HVACMode.OFF: 0,
    HVACMode.FAN_ONLY: 1,
    HVACMode.COOL: 2,
    HVACMode.HEAT: 4,
    HVACMode.DRY: 6,
    HVACMode.AUTO: 11,
}
EASY_MODE_TO_HA_MODE = {v: k for k, v in HA_MODE_TO_EASY_MODE.items()}

FAN_MODES = {
    "off": 0,
    "manualL": 1,
    "manualH": 2,
    "cycledL": 65,
    "cycledH": 66,
    "full auto": 128,
}
FAN_MODES_REVERSE = {v: k for k, v in FAN_MODES.items()}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MicroAirEasyTouch climate platform."""
    data = hass.data[DOMAIN][config_entry.entry_id]["data"]
    entity = MicroAirEasyTouchClimate(data, config_entry.unique_id)
    async_add_entities([entity])
    await entity.async_start_notifications()

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
        HVACMode.DRY,
    ]
    _attr_fan_modes = list(FAN_MODES.keys())

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
        self._notification_active = False

    async def async_start_notifications(self) -> None:
        """Start subscribing to notifications from the device."""
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.error("Could not find BLE device: %s", self._mac_address)
            return

        try:
            await self._data.start_notifications(
                self.hass,
                ble_device,
                self._handle_notification,
            )
            self._notification_active = True
            await self._async_fetch_initial_state()
            _LOGGER.debug("Notifications started for %s", self._mac_address)
        except Exception as e:
            _LOGGER.error("Failed to start notifications: %s", str(e))
            self._notification_active = False

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup when entity is removed."""
        await self._data.stop_notifications(self.hass)
        self._notification_active = False
        await super().async_will_remove_from_hass()

    @callback
    def _handle_notification(self, data: bytes) -> None:
        """Handle incoming notification data."""
        try:
            decrypted_data = self._data.decrypt(data.decode('utf-8'))
            self._state = decrypted_data
            _LOGGER.debug("Received notification update: %s", self._state)
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("Error processing notification: %s", str(e))
            self._state = {}
            self.async_write_ha_state()

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
    def available(self) -> bool:
        """Return if entity is available."""
        return self._notification_active and bool(self._state)

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
        mode = self._state.get("mode", "off")
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
        elif mode == "dry":
            return HVACMode.DRY
        return HVACMode.OFF

    @property
    def fan_mode(self) -> str | None:
        """Return the fan setting."""
        return self._state.get("fan_mode", "full auto")

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

        fan_value = FAN_MODES.get(fan_mode)
        if fan_value is not None:
            message = {"Type": "Change", "Changes": {"zone": 0, "fanOnly": fan_value}}
            await self._data.send_command(self.hass, ble_device, message)

    async def async_update(self) -> None:
        """Update the entity state manually if needed."""
        await self._async_fetch_initial_state()