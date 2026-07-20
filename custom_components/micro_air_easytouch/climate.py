"""Support for MicroAirEasyTouch climate control."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .micro_air_easytouch.const import (
    EASY_MODE_TO_HA_MODE,
    FAN_MODES_FAN_ONLY,
    FAN_MODES_REVERSE,
    HA_MODE_TO_EASY_MODE,
)
from .micro_air_easytouch.parser import MicroAirEasyTouchBluetoothDeviceData

_LOGGER = logging.getLogger(__name__)

# Reuse device state fetched within this window (by any zone entity) instead
# of opening another BLE connection. Must be shorter than the entity poll
# interval so a regular poll cycle still refreshes the state exactly once.
STATE_MAX_AGE_SECONDS = 25.0


def _use_legacy_identity(hass: HomeAssistant, mac_address: str, zone: int) -> bool:
    """Determine whether a single-zone device should use the legacy identity.

    Users upgrading from pre-0.3.0 releases have an entity registered with the
    legacy unique_id, while users of the experimental multi-zone build
    (experimental-pr24-multizone) already have a per-zone unique_id. Keep
    whichever identity is already in the registry so neither group's
    configuration breaks. New installs default to the legacy identity.
    """
    registry = er.async_get(hass)
    legacy_unique_id = f"microaireasytouch_{mac_address}_climate"
    zone_unique_id = f"microaireasytouch_{mac_address}_climate_zone_{zone}"
    if registry.async_get_entity_id("climate", DOMAIN, legacy_unique_id):
        return True
    if registry.async_get_entity_id("climate", DOMAIN, zone_unique_id):
        return False
    return True


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
        # Fall back to a single entity if device not found
        async_add_entities(
            [
                MicroAirEasyTouchClimate(
                    data,
                    mac_address,
                    0,
                    use_legacy_identity=_use_legacy_identity(hass, mac_address, 0),
                )
            ]
        )
        return

    # Probe device for available zones
    try:
        available_zones = await data.get_available_zones(hass, ble_device)
        _LOGGER.info("Detected zones for device %s: %s", mac_address, available_zones)
        if len(available_zones) <= 1:
            # Single-zone device: keep whichever entity identity is already
            # registered (pre-0.3.0 legacy or experimental multi-zone build)
            # so existing Home Assistant configurations keep working.
            zone = available_zones[0] if available_zones else 0
            async_add_entities(
                [
                    MicroAirEasyTouchClimate(
                        data,
                        mac_address,
                        zone,
                        use_legacy_identity=_use_legacy_identity(
                            hass, mac_address, zone
                        ),
                    )
                ]
            )
        else:
            async_add_entities(
                MicroAirEasyTouchClimate(data, mac_address, zone)
                for zone in available_zones
            )
    except Exception as e:
        _LOGGER.error("Failed to detect zones for device %s: %s", mac_address, str(e))
        # Fall back to a single entity if detection fails
        async_add_entities(
            [
                MicroAirEasyTouchClimate(
                    data,
                    mac_address,
                    0,
                    use_legacy_identity=_use_legacy_identity(hass, mac_address, 0),
                )
            ]
        )


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

    def __init__(
        self,
        data: MicroAirEasyTouchBluetoothDeviceData,
        mac_address: str,
        zone: int,
        use_legacy_identity: bool = False,
    ) -> None:
        """Initialize the climate."""
        self._data = data
        self._mac_address = mac_address
        self._zone = zone
        if use_legacy_identity:
            # Preserve the pre-0.3.0 (single zone) unique_id, name and
            # device so upgrades don't break existing configurations.
            self._attr_unique_id = f"microaireasytouch_{mac_address}_climate"
            self._attr_name = "EasyTouch Climate"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"MicroAirEasyTouch_{mac_address}")},
                name=f"EasyTouch {mac_address}",
                manufacturer="Micro-Air",
                model="Thermostat",
            )
        else:
            self._attr_unique_id = (
                f"microaireasytouch_{mac_address}_climate_zone_{zone}"
            )
            self._attr_name = f"Zone {zone}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"MicroAirEasyTouch_{mac_address}_zone_{zone}")},
                name=f"EasyTouch Zone {zone}",
                manufacturer="Micro-Air",
                model="EasyTouch Thermostat Zone",
                via_device=(DOMAIN, f"MicroAirEasyTouch_{mac_address}"),
            )
        self._state = {}
        # Availability is tracked separately from _state so a transient poll
        # failure (missed advertisement, GATT timeout) surfaces as
        # "unavailable" rather than collapsing the entity to hvac_mode=off /
        # temperature=None. See #27.
        self._attr_available = False

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

    @callback
    def _handle_data_update(self) -> None:
        """Refresh this zone's state when the shared device state changes.

        Called whenever any zone entity (or the initial zone probe)
        successfully fetches full device status, so every zone stays in sync
        from a single BLE transaction.
        """
        full_data = self._data.current_state
        if full_data and self._zone in full_data.get("zones", {}):
            self._state = full_data["zones"][self._zone]
            self._attr_available = True
            self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register callback for shared device state updates."""
        self._data.register_callback(self._handle_data_update)
        # Apply any state already fetched during zone detection
        self._handle_data_update()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        self._data.unregister_callback(self._handle_data_update)

    async def _async_fetch_state(self) -> None:
        """Fetch the current state from the device.

        On any failure (device not currently visible to the scanner, GATT
        timeout, etc.) the previous self._state is kept as-is and only
        _attr_available is flipped, so a transient miss shows as
        "unavailable" instead of resetting the thermostat to hvac_mode=off.
        """
        ble_device = async_ble_device_from_address(self.hass, self._mac_address)
        if not ble_device:
            _LOGGER.debug("BLE device not currently visible: %s", self._mac_address)
            self._attr_available = False
            self.async_write_ha_state()
            return

        try:
            full_data = await self._data.get_zone_status(
                self.hass, ble_device, self._zone, max_age=STATE_MAX_AGE_SECONDS
            )
            if full_data:
                # Get zone-specific data
                if self._zone in full_data.get("zones", {}):
                    self._state = full_data["zones"][self._zone]
                else:
                    # Fall back to root level data (backward compatibility)
                    self._state = full_data
                self._attr_available = True
                _LOGGER.debug("State fetched for zone %s: %s", self._zone, self._state)
            else:
                _LOGGER.debug("Failed to fetch status for zone %s", self._zone)
                self._attr_available = False
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("Failed to fetch state for zone %s: %s", self._zone, str(e))
            self._attr_available = False
            self.async_write_ha_state()

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
            message = {
                "Type": "Change",
                "Changes": {"zone": self._zone, "fanOnly": fan_value},
            }
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
        """Update the entity state on the regular poll cycle."""
        _LOGGER.debug("Updating state for zone %s", self._zone)
        await self._async_fetch_state()
