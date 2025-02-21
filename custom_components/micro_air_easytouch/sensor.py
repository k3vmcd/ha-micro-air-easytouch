"""Support for MicroAirEasyTouch sensors."""

from __future__ import annotations

import logging
_LOGGER = logging.getLogger(__name__)


from .micro_air_easytouch import MicroAirEasyTouchSensor, SensorUpdate

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.sensor import sensor_device_info_to_hass_device_info
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .device import device_key_to_bluetooth_entity_key
from .const import DOMAIN



SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    MicroAirEasyTouchSensor.FACE_PLATE_TEMPERATURE: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.FACE_PLATE_TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    MicroAirEasyTouchSensor.MODE: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.MODE,
        device_class=SensorDeviceClass.ENUM,
        options=["off", "fan", "cool", "cool_on", "heat", "heat_on", "auto"],
    ),

    MicroAirEasyTouchSensor.CURRENT_MODE: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.CURRENT_MODE,
        device_class=SensorDeviceClass.ENUM,
        options=["off", "fan", "cool", "cool_on", "heat", "heat_on", "auto"],
    ),

    MicroAirEasyTouchSensor.FAN_MODE: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.FAN_MODE,
        device_class=SensorDeviceClass.ENUM,
        options=["off", "manualL", "manualH", "cycledL", "cycledH", "full auto"],
    ),

    MicroAirEasyTouchSensor.AUTO_HEAT_SP: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.AUTO_HEAT_SP,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    MicroAirEasyTouchSensor.AUTO_COOL_SP: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.AUTO_COOL_SP,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    MicroAirEasyTouchSensor.COOL_SP: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.COOL_SP,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    MicroAirEasyTouchSensor.HEAT_SP: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.HEAT_SP,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    MicroAirEasyTouchSensor.DRY_SP: SensorEntityDescription(
        key=MicroAirEasyTouchSensor.DRY_SP,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),

}

MODE_ICONS = {
    "off": "mdi:power",
    "fan": "mdi:fan",
    "cool": "mdi:snowflake",
    "cool_on": "mdi:snowflake",
    "heat": "mdi:fire",
    "heat_on": "mdi:fire",
    "auto": "mdi:sun-snowflake"
}

CURRENT_MODE_ICONS = {
    "off": "mdi:power",
    "fan": "mdi:fan",
    "cool": "mdi:snowflake-thermometer",
    "cool_on": "mdi:snowflake-thermometer",
    "heat": "mdi:fire-circle",
    "heat_on": "mdi:fire-circle",
    "auto": "mdi:autorenew"
}

FAN_MODE_ICONS = {
    "off": "mdi:fan-off",
    "manualL": "mdi:fan-chevron-down",
    "manualH": "mdi:fan-chevron-up",
    "cycledL": "mdi:fan-minus",
    "cycledH": "mdi:fan-plus",
    "full auto": "mdi:fan-auto"
}

def sensor_update_to_bluetooth_data_update(
    sensor_update: SensorUpdate,
) -> PassiveBluetoothDataUpdate:
    """Convert a sensor update to a bluetooth data update."""
    return PassiveBluetoothDataUpdate(
        devices={
            device_id: sensor_device_info_to_hass_device_info(device_info)
            for device_id, device_info in sensor_update.devices.items()
        },
        entity_descriptions={
            device_key_to_bluetooth_entity_key(device_key): SENSOR_DESCRIPTIONS[
                device_key.key
            ]
            for device_key in sensor_update.entity_descriptions
        },
        entity_data={
            device_key_to_bluetooth_entity_key(device_key): sensor_values.native_value
            for device_key, sensor_values in sensor_update.entity_values.items()
        },
        entity_names={
            device_key_to_bluetooth_entity_key(device_key): sensor_values.name
            for device_key, sensor_values in sensor_update.entity_values.items()
        },
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MicroAirEasyTouch sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    data = hass.data[DOMAIN][config_entry.entry_id]["data"]

    entities = [
        MicroAirEasyTouchSensorEntity(coordinator, description, data)
        for description in SENSOR_DESCRIPTIONS.values()
    ]
    async_add_entities(entities)


class MicroAirEasyTouchSensorEntity(CoordinatorEntity, SensorEntity):
    """Representation of a MicroAirEasyTouch sensor."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: SensorEntityDescription,
        data: MicroAirEasyTouchBluetoothDeviceData | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._data = data
        self._attr_unique_id = f"{coordinator.name}_{description.key}"
        self._attr_name = description.name or description.key.replace("_", " ").title()  # Set friendly name
        if data:
            # Use getattr to safely access name and manufacturer, with fallbacks
            device_name = getattr(data, "name", f"EasyTouch_{coordinator.name.split('_')[-1]}")
            device_manufacturer = getattr(data, "manufacturer", "MicroAirEasyTouch")
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, coordinator.name)},
                name=device_name,
                manufacturer=device_manufacturer,
                model="Thermostat",
            )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._data is not None
    
    @property
    def icon(self) -> str:
        """Return the icon."""
        if self.entity_description.key == MicroAirEasyTouchSensor.MODE:
            return MODE_ICONS.get(self._attr_native_value, "mdi:thermostat")
        elif self.entity_description.key == MicroAirEasyTouchSensor.CURRENT_MODE:
            return CURRENT_MODE_ICONS.get(self._attr_native_value, "mdi:thermostat-box")
        elif self.entity_description.key == MicroAirEasyTouchSensor.FAN_MODE:
            return FAN_MODE_ICONS.get(self._attr_native_value, "mdi:fan")
        return None  # Let other sensors use their default icons

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self.coordinator.data:
            self._attr_native_value = None
            self.async_write_ha_state()
            return

        # Get the sensor key matching our entity
        sensor_key = self.entity_description.key
        
        # Find matching sensor data in coordinator update
        for device_key, value in self.coordinator.data.entity_data.items():
            if device_key.key == sensor_key:
                self._attr_native_value = value
                break
        
        self.async_write_ha_state()