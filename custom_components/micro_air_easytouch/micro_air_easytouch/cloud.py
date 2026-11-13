"""Micro-Air cloud communication for EasyTouch thermostats."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from functools import partial

import boto3
from awscrt.mqtt import QoS
from awsiot import mqtt_connection_builder
from pycognito import Cognito

from .parser import MicroAirEasyTouchBluetoothDeviceData

_LOGGER = logging.getLogger(__name__)

REGION = "us-east-1"
# Public application configuration embedded in the official EasyTouch mobile app.
USER_POOL_ID = "us-east-1_M9Hs9kugG"
CLIENT_ID = "2mfujqa7vidd2td9h08k9m061s"
CLIENT_SECRET = "bbq2v6edtn25j0pgdus7tsi4fq93rgiqfq0g0ener8m896o2euu"
IDENTITY_POOL_ID = "us-east-1:527ec272-ac1b-4301-8e46-464669790d6e"
IOT_ENDPOINT = "al2tvpwq2i0lf-ats.iot.us-east-1.amazonaws.com"
IOT_POLICY_NAME = "MyAndroidPolicy"
ACCOUNT_TABLE = "User_Accounts"
STATUS_TIMEOUT = 20


class CloudError(Exception):
    """Error communicating with the Micro-Air cloud."""


class CloudAuthenticationError(CloudError):
    """Error authenticating with the Micro-Air cloud."""


def _authenticate(email: str, password: str) -> tuple[Cognito, dict]:
    """Authenticate and exchange the user token for temporary AWS credentials."""
    cognito = Cognito(
        USER_POOL_ID,
        CLIENT_ID,
        user_pool_region=REGION,
        username=email,
        client_secret=CLIENT_SECRET,
    )
    try:
        cognito.authenticate(password)
    except Exception as exc:
        raise CloudAuthenticationError(type(exc).__name__) from exc

    login_key = f"cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
    try:
        identity = boto3.client("cognito-identity", region_name=REGION)
        identity_id = identity.get_id(
            IdentityPoolId=IDENTITY_POOL_ID,
            Logins={login_key: cognito.id_token},
        )["IdentityId"]
        credentials = identity.get_credentials_for_identity(
            IdentityId=identity_id,
            Logins={login_key: cognito.id_token},
        )["Credentials"]
    except Exception as exc:
        raise CloudError(type(exc).__name__) from exc
    return cognito, credentials


def _aws_client(service: str, credentials: dict):
    """Create an AWS client using temporary credentials."""
    return boto3.client(
        service,
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretKey"],
        aws_session_token=credentials["SessionToken"],
    )


def _read_account(credentials: dict, email: str) -> dict | None:
    """Read the account record containing the user's thermostats."""
    result = _aws_client("dynamodb", credentials).get_item(
        TableName=ACCOUNT_TABLE,
        Key={"email_address": {"S": email}},
    )
    return result.get("Item")


def _delete_certificate(iot, certificate: dict, attached: bool) -> bool:
    """Detach, deactivate, and delete a temporary MQTT certificate."""
    certificate_id = certificate["certificateId"]
    try:
        if attached:
            iot.detach_policy(
                policyName=IOT_POLICY_NAME,
                target=certificate["certificateArn"],
            )
        iot.update_certificate(certificateId=certificate_id, newStatus="INACTIVE")
        iot.delete_certificate(certificateId=certificate_id)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "Failed to delete temporary MQTT certificate: %s", type(exc).__name__
        )
        return False
    return True


class MicroAirEasyTouchCloudDeviceData(MicroAirEasyTouchBluetoothDeviceData):
    """EasyTouch device data transported over Micro-Air's AWS IoT service."""

    is_cloud = True

    def __init__(
        self,
        password: str,
        email: str,
        serial_number: str,
        control_type: str = "EasyTouch",
    ) -> None:
        """Initialize the cloud device."""
        super().__init__(password=password, email=email)
        self._serial_number = serial_number
        self._topic = f"{control_type} {serial_number}"
        self._connection = None
        self._iot = None
        self._certificate = None
        self._certificate_attached = False
        self._connected = asyncio.Event()
        self._status_received = asyncio.Event()
        self._hass = None
        self._loop = None
        self._stopping = False

    @staticmethod
    async def async_discover_things(
        hass,
        email: str,
        password: str,
    ) -> list[dict]:
        """Authenticate and return thermostats associated with the account."""
        cognito, credentials = await hass.async_add_executor_job(
            _authenticate, email, password
        )
        account_email = cognito.id_claims.get("email", email)
        item = await hass.async_add_executor_job(
            _read_account, credentials, account_email
        )
        if not item:
            return []
        try:
            return json.loads(item["Thing_list"]["S"]).get("Things", [])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CloudError("Invalid account response") from exc

    async def async_start(self, hass) -> None:
        """Authenticate, create a temporary certificate, and connect to MQTT."""
        self._hass = hass
        self._loop = asyncio.get_running_loop()
        self._stopping = False
        _, credentials = await hass.async_add_executor_job(
            _authenticate, self._email, self._password
        )
        self._iot = await hass.async_add_executor_job(_aws_client, "iot", credentials)
        self._certificate = await hass.async_add_executor_job(
            partial(self._iot.create_keys_and_certificate, setAsActive=True)
        )
        await hass.async_add_executor_job(
            partial(
                self._iot.attach_policy,
                policyName=IOT_POLICY_NAME,
                target=self._certificate["certificateArn"],
            )
        )
        self._certificate_attached = True
        self._connection = mqtt_connection_builder.mtls_from_bytes(
            cert_bytes=self._certificate["certificatePem"].encode(),
            pri_key_bytes=self._certificate["keyPair"]["PrivateKey"].encode(),
            endpoint=IOT_ENDPOINT,
            client_id=f"ha-easytouch-{uuid.uuid4()}",
            clean_session=True,
            keep_alive_secs=30,
            on_connection_interrupted=self._on_connection_interrupted,
            on_connection_resumed=self._on_connection_resumed,
        )
        await asyncio.wrap_future(self._connection.connect())
        self._connected.set()
        await self._subscribe()
        if await self.get_zone_status(hass, None, 0) is None:
            raise CloudError("Initial thermostat status request failed")

    async def async_stop(self) -> None:
        """Disconnect and delete the temporary MQTT certificate."""
        self._stopping = True
        self._connected.clear()
        if self._connection is not None:
            try:
                await asyncio.wrap_future(self._connection.disconnect())
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("MQTT disconnect failed: %s", type(exc).__name__)
            self._connection = None
        if self._iot is not None and self._certificate is not None:
            try:
                _, credentials = await self._hass.async_add_executor_job(
                    _authenticate, self._email, self._password
                )
                self._iot = await self._hass.async_add_executor_job(
                    _aws_client, "iot", credentials
                )
                deleted = await self._hass.async_add_executor_job(
                    _delete_certificate,
                    self._iot,
                    self._certificate,
                    self._certificate_attached,
                )
                if deleted:
                    self._certificate = None
                    self._certificate_attached = False
                    self._iot = None
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Certificate cleanup failed; retaining metadata for retry: %s",
                    type(exc).__name__,
                )
        else:
            self._iot = None

    def _on_connection_interrupted(self, connection, error, **kwargs) -> None:
        """Handle an MQTT interruption from the AWS CRT thread."""
        self._loop.call_soon_threadsafe(self._connected.clear)

    def _on_connection_resumed(
        self, connection, return_code, session_present, **kwargs
    ) -> None:
        """Handle an MQTT reconnection from the AWS CRT thread."""
        self._loop.call_soon_threadsafe(
            self._handle_connection_resumed, session_present
        )

    def _handle_connection_resumed(self, session_present: bool) -> None:
        """Restore state and subscriptions on the Home Assistant loop."""
        if self._stopping:
            return
        if session_present:
            self._connected.set()
        else:
            self._loop.create_task(self._resubscribe())

    async def _resubscribe(self) -> None:
        """Restore the thermostat subscription after reconnection."""
        try:
            async with self.lock:
                await self._subscribe()
                self._connected.set()
                await self._request_status_locked()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Failed to restore MQTT subscription: %s", type(exc).__name__)

    async def _subscribe(self) -> None:
        """Subscribe to thermostat responses."""
        future, _ = self._connection.subscribe(
            self._topic, QoS.AT_MOST_ONCE, self._on_payload
        )
        await asyncio.wrap_future(future)

    def _on_payload(self, topic: str, payload: bytes, **kwargs) -> None:
        """Queue an MQTT payload on the Home Assistant loop."""
        self._loop.call_soon_threadsafe(self._handle_payload, payload)

    def _handle_payload(self, payload: bytes) -> None:
        """Parse and share a fresh thermostat status response."""
        try:
            status = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _LOGGER.debug("Received invalid JSON from EasyTouch cloud")
            return
        if status.get("Type") != "Response" or status.get("RT") != "Status":
            return
        decrypted = self.decrypt(payload.decode("utf-8"))
        if not decrypted or not any(decrypted.get("zones", {}).values()):
            _LOGGER.debug("EasyTouch cloud returned no usable zone data")
            return
        self.current_state = decrypted
        self._last_status_time = time.monotonic()
        self._status_received.set()
        self._notify_callbacks()

    async def _ensure_connected(self) -> None:
        """Wait for the active MQTT connection or its automatic reconnect."""
        if self._connection is None or self._stopping:
            raise CloudError("Cloud connection is not running")
        if not self._connected.is_set():
            try:
                await asyncio.wait_for(self._connected.wait(), STATUS_TIMEOUT)
            except TimeoutError as exc:
                raise CloudError("Cloud connection is unavailable") from exc

    async def _publish(self, message: dict) -> None:
        """Publish a command to the thermostat topic."""
        await self._ensure_connected()
        future, _ = self._connection.publish(
            self._topic, json.dumps(message), QoS.AT_MOST_ONCE
        )
        await asyncio.wrap_future(future)

    async def _request_status_locked(self) -> dict:
        """Request fresh status. Caller must hold self.lock."""
        self._status_received.clear()
        await self._publish(
            {
                "Type": "Get Status",
                "Zone": 0,
                "EM": self._email,
                "TM": int(time.time()),
            }
        )
        try:
            await asyncio.wait_for(self._status_received.wait(), STATUS_TIMEOUT)
        except TimeoutError as exc:
            raise CloudError("Timed out waiting for thermostat status") from exc
        return self.current_state

    async def get_available_zones(self, hass, ble_device=None) -> list[int]:
        """Return zones from a fresh full-device status response."""
        status = await self.get_zone_status(hass, None, 0)
        return status.get("available_zones", [0])

    async def get_zone_status(
        self, hass, ble_device=None, zone: int = 0, max_age: float = 0.0
    ) -> dict | None:
        """Return shared device state, refreshing it when stale."""
        async with self.lock:
            if (
                max_age > 0
                and self.current_state
                and time.monotonic() - self._last_status_time < max_age
            ):
                return self.current_state
            try:
                return await self._request_status_locked()
            except CloudError as exc:
                _LOGGER.debug("Cloud status request failed: %s", exc)
                return None

    async def send_command(
        self, hass, ble_device=None, command: dict | None = None
    ) -> bool:
        """Send a command and refresh thermostat state after changes."""
        if command is None:
            return False
        async with self.lock:
            try:
                await self._publish(command)
                if command.get("Type") == "Change":
                    self._last_status_time = 0.0
                    await asyncio.sleep(0.5)
                    await self._request_status_locked()
                return True
            except CloudError as exc:
                _LOGGER.warning("Cloud command failed: %s", exc)
                return False

    async def reboot_device(self, hass, ble_device=None) -> bool:
        """Reboot the thermostat without waiting for a subsequent status."""
        async with self.lock:
            try:
                await self._publish(
                    {"Type": "Change", "Changes": {"zone": 0, "reset": " OK"}}
                )
                self._last_status_time = 0.0
                return True
            except CloudError as exc:
                _LOGGER.warning("Cloud reboot failed: %s", exc)
                return False
