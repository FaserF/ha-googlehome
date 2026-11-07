"""API Client for Google Home devices through glocaltokens and local REST."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from glocaltokens.client import GLocalAuthenticationTokens

from ..const import (
    JSON_ALARM,
    JSON_ALARM_VOLUME,
    JSON_NOTIFICATIONS_ENABLED,
    JSON_TIMER,
)
from ..firmware import extract_firmware_versions
from ..local_cast import read_cast_volume
from ..volume import read_volume_percentage
from .auth import AuthMixin
from .discovery import DiscoveryMixin
from .operations import OperationsMixin

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.core import HomeAssistant
    from zeroconf import Zeroconf

    from ..models import GoogleHomeDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GlocaltokensApiClient(AuthMixin, DiscoveryMixin, OperationsMixin):
    """API client for Google Home devices through glocaltokens and local REST."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        username: str | None = None,
        password: str | None = None,
        master_token: str | None = None,
        android_id: str | None = None,
        zeroconf_instance: Zeroconf | None = None,
        selected_homes: list[str] | None = None,
        known_hosts: list[str] | None = None,
    ):
        """Initialize the API client."""
        self.hass = hass
        self._session = session
        self.username = username
        self.password = password
        self.master_token = master_token
        self.android_id = android_id
        self.zeroconf_instance = zeroconf_instance
        self.selected_homes = selected_homes
        self.known_hosts: list[str] = known_hosts or []
        self.google_devices: list[GoogleHomeDevice] = []
        self._discovery_ids: dict[str, str] = {}
        self._address_discovery_lock = asyncio.Lock()
        self._last_address_discovery: float | None = None

        # Browser OAuth cookies must be exchanged before they become master tokens.
        is_web_token = bool(
            master_token and master_token.startswith(("oauth2_4/", "1//"))
        )
        self._client = GLocalAuthenticationTokens(
            username=username,
            password=password,
            master_token=None if is_web_token else master_token,
            oauth_token=master_token if is_web_token else None,
            android_id=android_id,
            verbose=False,
        )

    async def update_google_devices_information(self) -> list[GoogleHomeDevice]:
        """Update data for all Google Home devices concurrently."""
        devices = await self.get_google_devices()
        tasks = [self.update_device_data(device) for device in devices]
        await asyncio.gather(*tasks, return_exceptions=True)
        return devices

    async def update_device_data(self, device: GoogleHomeDevice) -> None:
        """Update state and information for a single Google Home device."""
        if not device.ip_address:
            _LOGGER.debug("Device %s missing IP address", device.name)
            device.available = False
            device.direct_cast_status = "missing_ip"
            device.clear_device_volume()
            return
        if not device.auth_token:
            _LOGGER.debug("Device %s missing local HTTP auth token", device.name)
            device.available = False
            await self._update_direct_cast_volume(device)
            return

        media_volume_read = False
        try:
            # Poll Alarms & Timers & Alarm Volume
            alarms_data = await self.get_alarms_and_timers(device)
            alarm_vol_found = False
            if alarms_data:
                device.set_alarms(alarms_data.get(JSON_ALARM, []))
                device.set_timers(alarms_data.get(JSON_TIMER, []))
                if (
                    JSON_ALARM_VOLUME in alarms_data
                    and alarms_data[JSON_ALARM_VOLUME] is not None
                ):
                    raw_vol = alarms_data[JSON_ALARM_VOLUME]
                    # Google Home API returns volume as a float between 0.0 and 1.0 (e.g. 0.4 for 40%)
                    # or as a 0-100 percentage.
                    vol_pct = round(raw_vol * 100) if raw_vol <= 1.0 else round(raw_vol)
                    device.set_alarm_volume(vol_pct)
                    alarm_vol_found = True

            # If alarms response didn't include alarm volume, poll dedicated endpoint
            if not alarm_vol_found:
                try:
                    vol_data = await self.get_alarm_volume(device)
                    if vol_data and JSON_ALARM_VOLUME in vol_data:
                        raw_vol = vol_data[JSON_ALARM_VOLUME]
                        if raw_vol is not None:
                            vol_pct = (
                                round(raw_vol * 100)
                                if raw_vol <= 1.0
                                else round(raw_vol)
                            )
                            device.set_alarm_volume(vol_pct)
                except Exception:
                    pass

            # Poll Device Media / Speech Live Volume
            try:
                curr_vol_data = await self.get_current_device_volume(device)
                vol_pct = read_volume_percentage(curr_vol_data)
                if vol_pct is not None:
                    device.set_device_volume(vol_pct)
                    media_volume_read = True
            except Exception as err:
                _LOGGER.debug("Media volume read failed for %s: %s", device.name, err)

            # Poll Do Not Disturb
            dnd_data = await self.get_do_not_disturb(device)
            if dnd_data and JSON_NOTIFICATIONS_ENABLED in dnd_data:
                device.set_do_not_disturb(not dnd_data[JSON_NOTIFICATIONS_ENABLED])

            # Poll Night Mode Settings
            night_mode_data = await self.get_night_mode_settings(device)
            if night_mode_data and "enabled" in night_mode_data:
                device.set_night_mode(bool(night_mode_data["enabled"]))

            # Poll Eureka Info (Wi-Fi SSID, RSSI, Bluetooth MAC, Firmware Version, Audio Volume)
            eureka_data = await self.get_eureka_info(device)
            if eureka_data:
                # Also check audio block in eureka_info as backup/supplemental volume source
                audio_data = eureka_data.get("audio") or {}
                if not media_volume_read:
                    vol_pct = read_volume_percentage(audio_data)
                    if vol_pct is not None:
                        device.set_device_volume(vol_pct, source="eureka_audio")
                        media_volume_read = True

                wifi_data = (
                    eureka_data.get("wifi")
                    or eureka_data.get("wlan")
                    or eureka_data.get("net", {}).get("wifi")
                    or eureka_data.get("net", {}).get("wlan")
                    or {}
                )
                net_data = eureka_data.get("net") or {}

                # Extract SSID
                raw_ssid = (
                    wifi_data.get("ssid")
                    or wifi_data.get("wlan_ssid")
                    or net_data.get("ssid")
                    or eureka_data.get("ssid")
                )

                # Extract Signal Level (dBm or percentage)
                raw_rssi = (
                    wifi_data.get("signal_level")
                    or wifi_data.get("rssi")
                    or wifi_data.get("signal")
                    or net_data.get("signal_level")
                    or net_data.get("rssi")
                    or eureka_data.get("signal_level")
                )
                rssi_int = None
                if raw_rssi is not None:
                    try:
                        rssi_int = int(raw_rssi)
                    except (ValueError, TypeError):
                        pass

                device.set_wifi_info(
                    ssid=str(raw_ssid) if raw_ssid is not None else None,
                    rssi=rssi_int,
                )
                raw_bssid = (
                    wifi_data.get("bssid")
                    or net_data.get("bssid")
                    or eureka_data.get("bssid")
                )
                device.wifi_bssid = str(raw_bssid) if raw_bssid else None

                uptime = eureka_data.get("uptime")
                if uptime is None and isinstance(eureka_data.get("device_info"), dict):
                    uptime = eureka_data["device_info"].get("uptime")
                device.set_uptime(uptime)

                device_info = eureka_data.get("device_info") or {}
                cast_uuid = (
                    eureka_data.get("ssdp_udn")
                    or eureka_data.get("cast_uuid")
                    or eureka_data.get("uuid")
                    or device_info.get("ssdp_udn")
                    or device_info.get("cast_uuid")
                    or device_info.get("uuid")
                )
                if cast_uuid and isinstance(cast_uuid, str):
                    if cast_uuid.lower().startswith("uuid:"):
                        cast_uuid = cast_uuid[5:]
                    cast_uuid = cast_uuid.replace("-", "").strip()

                firmware, cast_firmware, system_firmware = extract_firmware_versions(
                    eureka_data
                )
                net_mac = (
                    (
                        net_data.get("ethernet", {}).get("mac_address")
                        if isinstance(net_data.get("ethernet"), dict)
                        else None
                    )
                    or (
                        net_data.get("wlan", {}).get("mac_address")
                        if isinstance(net_data.get("wlan"), dict)
                        else None
                    )
                    or net_data.get("mac_address")
                    or wifi_data.get("mac_address")
                    or eureka_data.get("mac_address")
                    or device_info.get("mac_address")
                )
                # Extract OTA status and has_update if reported by device
                ota_data = (
                    eureka_data.get("ota")
                    or eureka_data.get("setup", {}).get("ota")
                    or {}
                )
                ota_status = None
                if isinstance(ota_data, dict):
                    ota_status = (
                        ota_data.get("status")
                        or ota_data.get("download_progress")
                        or ota_data.get("state")
                    )
                elif isinstance(ota_data, str):
                    ota_status = ota_data

                raw_has_update = eureka_data.get("has_update")
                if raw_has_update is None and isinstance(ota_data, dict):
                    raw_has_update = ota_data.get("has_update")
                has_update = (
                    bool(raw_has_update) if raw_has_update is not None else None
                )

                fw_str = str(firmware) if firmware else None

                device.set_system_info(
                    firmware=fw_str,
                    cast_firmware=cast_firmware,
                    system_firmware=system_firmware,
                    mac=str(net_mac) if net_mac else None,
                    cast_uuid=cast_uuid if cast_uuid else None,
                    ota_status=str(ota_status) if ota_status else None,
                    has_update=has_update,
                    latest_firmware=fw_str,
                )

                bt_data = eureka_data.get("bluetooth") or {}
                bt_mac = (
                    bt_data.get("mac_address")
                    or bt_data.get("device_address")
                    or device_info.get("mac_address")
                    or eureka_data.get("mac_address")
                )
                if not bt_mac:
                    try:
                        bt_status = await self.get_bluetooth_status(device)
                        if bt_status:
                            bt_mac = bt_status.get("mac_address") or bt_status.get(
                                "device_address"
                            )
                    except Exception:
                        pass
                device.set_bluetooth_mac(bt_mac)

            device.available = True
        except Exception as err:
            _LOGGER.debug(
                "Device %s (%s) is offline or unreachable: %s",
                device.name,
                device.ip_address,
                err,
            )
            device.available = False

        if not media_volume_read:
            await self._update_direct_cast_volume(device)
        else:
            device.direct_cast_status = "not_needed"

    async def _update_direct_cast_volume(self, device: GoogleHomeDevice) -> None:
        """Fall back to the local receiver socket independently of HTTP auth/Cast HA."""
        volume = await self.get_direct_device_volume(device)
        if volume is not None:
            device.set_device_volume(volume, source="cast_direct")
        else:
            device.clear_device_volume()

    async def get_direct_device_volume(self, device: GoogleHomeDevice) -> float | None:
        """Read Cast status on a worker without depending on a media_player entity."""
        if not device.ip_address:
            device.direct_cast_status = "missing_ip"
            return None
        if not device.cast_uuid:
            device.direct_cast_status = "missing_identity"
            return None
        try:
            volume = await self.hass.async_add_executor_job(
                read_cast_volume,
                device.ip_address,
                device.cast_uuid,
                device.model_name,
                device.name,
            )
        except Exception as err:
            _LOGGER.debug(
                "Direct Cast volume polling failed for %s: %s",
                device.name,
                err,
                exc_info=True,
            )
            volume = None
        device.direct_cast_status = "ready" if volume is not None else "unavailable"
        return volume
