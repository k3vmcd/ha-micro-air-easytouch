"""Config flow for MicroAirEasyTouch integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_CONTROL_TYPE,
    CONN_TYPE_BLE,
    CONN_TYPE_CLOUD,
    DOMAIN,
)
from .micro_air_easytouch.cloud import (
    CloudAuthenticationError,
    CloudError,
    MicroAirEasyTouchCloudDeviceData,
)
from .micro_air_easytouch.parser import MicroAirEasyTouchBluetoothDeviceData

_LOGGER = logging.getLogger(__name__)


class MicroAirEasyTouchConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MicroAirEasyTouch."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_device: MicroAirEasyTouchBluetoothDeviceData | None = None
        self._discovered_devices: dict[str, str] = {}
        self._ble_discovery_info: dict[str, BluetoothServiceInfoBleak] = {}
        self._cloud_email: str | None = None
        self._cloud_password: str | None = None
        self._cloud_things: list[dict] = []
        self._reconfigure_entry = None

    def _other_config_entries(self) -> list:
        """Return entries other than the one being reconfigured."""
        current_entry_id = (
            self._reconfigure_entry.entry_id if self._reconfigure_entry else None
        )
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id != current_entry_id
        ]

    def _address_is_configured(self, address: str) -> bool:
        """Return whether another entry already uses this transport address."""
        return any(
            address in (entry.unique_id, entry.data.get(CONF_ADDRESS))
            for entry in self._other_config_entries()
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Replace an existing connection with cloud without recreating entities."""
        self._reconfigure_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user(user_input)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the thermostat connection type."""
        if user_input is not None:
            if user_input[CONF_CONNECTION_TYPE] == CONN_TYPE_CLOUD:
                return await self.async_step_cloud()
            return await self.async_step_ble()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONNECTION_TYPE, default=CONN_TYPE_BLE): vol.In(
                        {
                            CONN_TYPE_BLE: "Bluetooth Low Energy",
                            CONN_TYPE_CLOUD: "Micro-Air Cloud",
                        }
                    )
                }
            ),
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Authenticate with Micro-Air and list account thermostats."""
        errors = {}
        if user_input is not None:
            self._cloud_email = user_input[CONF_USERNAME]
            self._cloud_password = user_input[CONF_PASSWORD]
            try:
                self._cloud_things = (
                    await MicroAirEasyTouchCloudDeviceData.async_discover_things(
                        self.hass, self._cloud_email, self._cloud_password
                    )
                )
                if not self._cloud_things:
                    errors["base"] = "no_devices_found"
                else:
                    return await self.async_step_cloud_device()
            except CloudAuthenticationError:
                errors["base"] = "invalid_auth"
            except CloudError:
                errors["base"] = "cannot_connect"
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Cloud discovery failed: %s", type(exc).__name__)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_cloud_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select a thermostat from the cloud account."""
        devices = {
            thing["Serial_number"]: thing.get("Name")
            or f"EasyTouch {thing['Serial_number']}"
            for thing in self._cloud_things
        }
        if user_input is not None:
            serial_number = user_input[CONF_ADDRESS]
            thing = next(
                item
                for item in self._cloud_things
                if item["Serial_number"] == serial_number
            )
            if self._address_is_configured(serial_number):
                return self.async_abort(reason="already_configured")

            data = {
                CONF_USERNAME: self._cloud_email,
                CONF_PASSWORD: self._cloud_password,
                CONF_ADDRESS: serial_number,
                CONF_CONTROL_TYPE: thing.get("Control_Type", "EasyTouch"),
                CONF_CONNECTION_TYPE: CONN_TYPE_CLOUD,
            }
            cloud = MicroAirEasyTouchCloudDeviceData(
                password=self._cloud_password,
                email=self._cloud_email,
                serial_number=serial_number,
                control_type=data[CONF_CONTROL_TYPE],
            )
            try:
                await cloud.async_start(self.hass)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Cloud thermostat validation failed: %s", type(exc).__name__
                )
                return self.async_show_form(
                    step_id="cloud_device",
                    data_schema=vol.Schema(
                        {vol.Required(CONF_ADDRESS): vol.In(devices)}
                    ),
                    errors={"base": "cannot_connect"},
                )
            finally:
                await cloud.async_stop()

            if self._reconfigure_entry is not None:
                return self.async_update_reload_and_abort(
                    self._reconfigure_entry,
                    title=devices[serial_number],
                    data=data,
                    reason="reconfigure_successful",
                )

            await self.async_set_unique_id(serial_number, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=devices[serial_number], data=data)

        return self.async_show_form(
            step_id="cloud_device",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(devices)}),
        )

    async def async_step_ble(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick a discovered BLE device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if self._address_is_configured(address):
                return self.async_abort(reason="already_configured")
            if self._reconfigure_entry is None:
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
            self._discovery_info = self._ble_discovery_info[address]
            device = MicroAirEasyTouchBluetoothDeviceData(password=None, email=None)
            self._discovered_device = device
            return await self.async_step_password()

        current_addresses = {
            value
            for entry in self._other_config_entries()
            for value in (entry.unique_id, entry.data.get(CONF_ADDRESS))
            if value
        }
        for discovery_info in async_discovered_service_info(self.hass, False):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_devices:
                continue
            device = MicroAirEasyTouchBluetoothDeviceData(password=None)
            if device.supported(discovery_info):
                self._ble_discovery_info[address] = discovery_info
                self._discovered_devices[address] = (
                    device.title or device.get_device_name() or discovery_info.name
                )

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="ble",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered_devices)}
            ),
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        device = MicroAirEasyTouchBluetoothDeviceData(password=None, email=None)
        if not device.supported(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery_info = discovery_info
        self._discovered_device = device
        return await self.async_step_password()

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle password and email entry."""
        errors = {}
        if user_input is not None:
            try:
                assert self._discovered_device is not None
                self._discovered_device._email = user_input[CONF_USERNAME]
                self._discovered_device._password = user_input[CONF_PASSWORD]
                return await self.async_step_bluetooth_confirm(user_input)
            except Exception:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        assert self._discovered_device is not None
        device = self._discovered_device
        assert self._discovery_info is not None
        discovery_info = self._discovery_info
        title = device.title or device.get_device_name() or discovery_info.name
        if user_input is not None:
            data = {
                CONF_USERNAME: self._discovered_device._email,
                CONF_PASSWORD: self._discovered_device._password,
                CONF_ADDRESS: discovery_info.address,
                CONF_CONNECTION_TYPE: CONN_TYPE_BLE,
            }
            if self._reconfigure_entry is not None:
                return self.async_update_reload_and_abort(
                    self._reconfigure_entry,
                    title=title,
                    data=data,
                    reason="reconfigure_successful",
                )
            return self.async_create_entry(title=title, data=data)

        self._set_confirm_only()
        placeholders = {"name": title}
        self.context["title_placeholders"] = placeholders
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders=placeholders
        )
