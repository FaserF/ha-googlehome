"""Device operations and HTTP request mixin for Google Home API client."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp

from ..const import (
    API_ENDPOINT_ALARM_DELETE,
    API_ENDPOINT_ALARM_VOLUME,
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_BLUETOOTH_STATUS,
    API_ENDPOINT_CURRENT_VOLUME,
    API_ENDPOINT_DEVICE_INFO,
    API_ENDPOINT_DO_NOT_DISTURB,
    API_ENDPOINT_NIGHT_MODE_SETTINGS,
    API_ENDPOINT_REBOOT,
    API_ENDPOINT_SET_VOLUME,
    DEFAULT_TIMEOUT,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
    JSON_ALARM_VOLUME,
    JSON_NIGHT_MODE_ENABLED,
    JSON_NOTIFICATIONS_ENABLED,
    PORT,
)
from ..exceptions import DeviceConnectionError
from ..volume import read_volume_percentage

if TYPE_CHECKING:
    from ..models import GoogleHomeDevice
    from ..types import JsonDict

_LOGGER: logging.Logger = logging.getLogger(__package__)


class OperationsMixin:
    """Mixin providing local device HTTP operations."""

    _session: aiohttp.ClientSession

    async def get_google_devices(
        self, force_reload: bool = False
    ) -> list[GoogleHomeDevice]:
        """Declared for type checkers; implemented in DiscoveryMixin."""
        raise NotImplementedError

    async def _async_resolve_missing_addresses(
        self, devices: list[GoogleHomeDevice]
    ) -> None:
        """Declared for type checkers; implemented in DiscoveryMixin."""
        raise NotImplementedError

    def create_url(self, ip_address: str, endpoint: str) -> str:
        """Create URL for device HTTP request, properly escaping IPv6 if present."""
        host = (
            f"[{ip_address}]"
            if ":" in ip_address and not ip_address.startswith("[")
            else ip_address
        )
        return f"https://{host}:{PORT}/{endpoint}"

    def create_headers(self, auth_token: str | None) -> dict[str, str]:
        """Create headers for request."""
        headers = {
            HEADER_CONTENT_TYPE: "application/json",
        }
        if auth_token:
            headers[HEADER_CAST_LOCAL_AUTH] = auth_token
        return headers

    async def _request(
        self,
        method: str,
        device: GoogleHomeDevice,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> JsonDict | None:
        """Make an authenticated HTTP request to device local API."""
        if not device.ip_address:
            await self._async_resolve_missing_addresses([device])
        if not device.ip_address:
            raise DeviceConnectionError(
                f"No IP address for {device.name} after local discovery. "
                "Check that Home Assistant can receive this device's mDNS announcements."
            )

        url = self.create_url(device.ip_address, endpoint)
        headers = self.create_headers(device.auth_token)

        try:
            timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data,
                ssl=False,
                timeout=timeout,
            ) as response:
                if response.status == HTTPStatus.UNAUTHORIZED and retry_auth:
                    _LOGGER.info(
                        "Token expired for %s, refreshing Google devices...",
                        device.name,
                    )
                    await self.get_google_devices(force_reload=True)
                    return await self._request(
                        method, device, endpoint, json_data, retry_auth=False
                    )

                if response.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    if response.content_type == "application/json":
                        return await response.json()
                    return {}

                _LOGGER.debug("Request to %s returned status %d", url, response.status)
                return None
        except (TimeoutError, aiohttp.ClientError) as err:
            raise DeviceConnectionError(
                f"Error communicating with {device.name}: {err}"
            ) from err

    async def get_alarms_and_timers(self, device: GoogleHomeDevice) -> JsonDict | None:
        """Get alarms and timers from device."""
        return await self._request("GET", device, API_ENDPOINT_ALARMS)

    async def get_alarm_volume(self, device: GoogleHomeDevice) -> JsonDict | None:
        """Get alarm volume from device."""
        alarms_data = await self.get_alarms_and_timers(device)
        if alarms_data and JSON_ALARM_VOLUME in alarms_data:
            return {JSON_ALARM_VOLUME: alarms_data[JSON_ALARM_VOLUME]}
        return await self._request("GET", device, API_ENDPOINT_ALARM_VOLUME)

    async def set_alarm_volume(
        self, device: GoogleHomeDevice, volume: float
    ) -> JsonDict | None:
        """Set alarm volume on device (0.0 - 1.0)."""
        return await self._request(
            "POST",
            device,
            API_ENDPOINT_ALARM_VOLUME,
            json_data={JSON_ALARM_VOLUME: volume},
        )

    async def update_alarm_volume(self, device: GoogleHomeDevice, volume: int) -> None:
        """Update alarm volume percentage (0-100) and update local device state."""
        float_volume = round(volume / 100, 2)
        await self.set_alarm_volume(device, float_volume)
        device.set_alarm_volume(volume)

    async def get_current_device_volume(
        self, device: GoogleHomeDevice
    ) -> JsonDict | None:
        """Get current live speaker / media volume."""
        for ep in (
            API_ENDPOINT_CURRENT_VOLUME,
            "setup/assistant/volume",
            "setup/audio/status",
        ):
            try:
                res = await self._request("GET", device, ep)
            except DeviceConnectionError as err:
                _LOGGER.debug(
                    "Media volume endpoint %s failed for %s: %s", ep, device.name, err
                )
                continue
            if read_volume_percentage(res) is not None:
                return res
        return None

    async def set_device_volume(
        self, device: GoogleHomeDevice, volume: float
    ) -> JsonDict | None:
        """Set normal speaker volume on device (0.0 - 1.0)."""
        payload = {"volume": volume, "level": volume}
        res = await self._request(
            "POST",
            device,
            API_ENDPOINT_SET_VOLUME,
            json_data=payload,
        )
        if res is None:
            res = await self._request(
                "POST",
                device,
                API_ENDPOINT_CURRENT_VOLUME,
                json_data=payload,
            )
        return res

    async def update_device_volume(
        self, device: GoogleHomeDevice, volume: int
    ) -> JsonDict | None:
        """Update normal speaker volume percentage (0-100) and sync local state."""
        float_volume = round(volume / 100, 2)
        res = await self.set_device_volume(device, float_volume)
        if res is not None:
            device.set_device_volume(volume, source="command")
        return res

    async def get_do_not_disturb(self, device: GoogleHomeDevice) -> JsonDict | None:
        """Get Do Not Disturb state."""
        return await self._request("GET", device, API_ENDPOINT_DO_NOT_DISTURB)

    async def set_do_not_disturb(
        self, device: GoogleHomeDevice, enable: bool
    ) -> JsonDict | None:
        """Set Do Not Disturb state on device."""
        # Note: notifications_enabled = False means Do Not Disturb is Active
        res = await self._request(
            "POST",
            device,
            API_ENDPOINT_DO_NOT_DISTURB,
            json_data={JSON_NOTIFICATIONS_ENABLED: not enable},
        )
        device.set_do_not_disturb(enable)
        return res

    async def delete_alarm_or_timer(
        self, device: GoogleHomeDevice, item_to_delete: str | list[str]
    ) -> JsonDict | None:
        """Delete an alarm or timer (or list of alarms/timers) from device."""
        ids = (
            [item_to_delete]
            if isinstance(item_to_delete, str)
            else list(item_to_delete)
        )
        if not ids:
            return None
        return await self._request(
            "POST",
            device,
            API_ENDPOINT_ALARM_DELETE,
            json_data={"ids": ids},
        )

    async def get_night_mode_settings(
        self, device: GoogleHomeDevice
    ) -> JsonDict | None:
        """Get Night Mode settings."""
        return await self._request("GET", device, API_ENDPOINT_NIGHT_MODE_SETTINGS)

    async def set_night_mode_enabled(
        self, device: GoogleHomeDevice, enable: bool
    ) -> JsonDict | None:
        """Enable or disable night mode on device."""
        res = await self._request(
            "POST",
            device,
            API_ENDPOINT_NIGHT_MODE_SETTINGS,
            json_data={JSON_NIGHT_MODE_ENABLED: enable},
        )
        device.set_night_mode(enable)
        return res

    async def get_eureka_info(self, device: GoogleHomeDevice) -> JsonDict | None:
        """Get device eureka_info (Wi-Fi, build, Bluetooth info)."""
        return await self._request("GET", device, API_ENDPOINT_DEVICE_INFO)

    async def get_bluetooth_status(self, device: GoogleHomeDevice) -> JsonDict | None:
        """Get Bluetooth status and paired devices."""
        return await self._request("GET", device, API_ENDPOINT_BLUETOOTH_STATUS)

    async def reboot_device(self, device: GoogleHomeDevice) -> JsonDict | None:
        """Reboot device."""
        return await self._request(
            "POST",
            device,
            API_ENDPOINT_REBOOT,
            json_data={"params": "now"},
        )

    async def broadcast_message(
        self, device: GoogleHomeDevice, message: str
    ) -> JsonDict | None:
        """Play local speech announcement or chime on Google Home device."""
        _LOGGER.info(
            "Sending broadcast '%s' to %s (%s)", message, device.name, device.ip_address
        )
        # Attempt local Assistant speech endpoint
        return await self._request(
            "POST",
            device,
            "setup/assistant/alarms",
            json_data={"custom_command": message},
        )
