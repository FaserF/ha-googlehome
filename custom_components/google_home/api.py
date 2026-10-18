"""API Client for Google Home."""

from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp
from glocaltokens.client import Device, GLocalAuthenticationTokens
from homeassistant.core import HomeAssistant
from zeroconf import Zeroconf

from .const import (
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
    DOMAIN,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
    JSON_ALARM,
    JSON_ALARM_VOLUME,
    JSON_NIGHT_MODE_ENABLED,
    JSON_NOTIFICATIONS_ENABLED,
    JSON_TIMER,
    PORT,
)
from .exceptions import (
    AdvancedProtectionActive,
    AuthenticationFailed,
    DeviceConnectionError,
    InvalidMasterToken,
    TwoFactorRequired,
)
from .firmware import extract_firmware_versions
from .local_cast import read_cast_volume
from .local_discovery import discover_cast_addresses, normalize_cast_uuid
from .models import GoogleHomeDevice
from .volume import read_volume_percentage

if TYPE_CHECKING:
    from .types import JsonDict

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Patch glocaltokens get_master_token so get_access_token() doesn't fail when password is None (Token auth)
_orig_get_master_token = GLocalAuthenticationTokens.get_master_token


def _safe_get_master_token(self: GLocalAuthenticationTokens) -> str | None:
    """Return stored master_token if present, otherwise invoke original method."""
    if getattr(self, "master_token", None):
        return self.master_token
    return _orig_get_master_token(self)


GLocalAuthenticationTokens.get_master_token = _safe_get_master_token  # type: ignore[method-assign]


class GlocaltokensApiClient:
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
        self.google_devices: list[GoogleHomeDevice] = []
        self._discovery_ids: dict[str, str] = {}
        self._address_discovery_lock = asyncio.Lock()
        self._last_address_discovery: float | None = None

        self._client = GLocalAuthenticationTokens(
            username=username,
            password=password,
            master_token=master_token,
            android_id=android_id,
            verbose=False,
        )

    async def async_get_available_homes(self) -> dict[str, str]:
        """Fetch dictionary of available home_id -> home_name from HomeGraph."""

        def _get_homes() -> dict[str, str]:
            homes: dict[str, str] = {}
            try:
                hg = self._client.get_homegraph()
                if hg and hasattr(hg, "home") and hg.home:
                    hid = getattr(hg.home, "home_id", "") or "default_home"
                    hname = getattr(hg.home, "home_name", "") or "My Google Home"
                    homes[hid] = hname

                    # Dynamically scan raw protobuf payload for all StructureTrait definitions
                    raw = hg.SerializeToString()
                    import re

                    found_names: list[str] = []
                    for match in re.finditer(
                        rb"StructureTrait[^\x00-\x1F]*\x12[\x01-\x20]\n\x04name\x12[\x01-\x20]\x1a[\x01-\x20]([^\x00-\x1F]+)",
                        raw,
                    ):
                        struct_name = match.group(1).decode("utf-8", errors="ignore")
                        if struct_name not in found_names:
                            found_names.append(struct_name)

                    # Correlate any rooms that belong to other structure UUIDs
                    other_structure_ids: list[str] = []
                    for r in getattr(hg.home, "rooms", []):
                        rid = getattr(r, "room_id", "")
                        if "." in rid:
                            prefix_uuid = rid.split(".")[0]
                            if (
                                prefix_uuid != hid
                                and prefix_uuid not in other_structure_ids
                            ):
                                other_structure_ids.append(prefix_uuid)

                    other_names = [n for n in found_names if n != hname]
                    for idx, sid in enumerate(other_structure_ids):
                        if idx < len(other_names):
                            homes[sid] = other_names[idx]
                        elif len(other_names) == 1:
                            homes[sid] = other_names[0]
                        else:
                            homes[sid] = f"Zuhause ({sid[:8]})"

                    return homes
            except Exception as exc:
                _LOGGER.debug(
                    "Could not fetch available homes in local client: %s", exc
                )
            return homes

        return await self.hass.async_add_executor_job(_get_homes)

    async def get_master_token(self) -> str:
        """Get master token (short-circuit if already available, PR #1042)."""
        if self.master_token:
            return self.master_token

        def _get_master_token() -> str | None:
            if not self.username or not self.password:
                return None
            try:
                from gpsoauth import perform_master_login

                res = perform_master_login(
                    self.username,
                    self.password,
                    self._client.get_android_id(),
                )
                if "Token" in res:
                    self.master_token = res["Token"]
                    self._client.master_token = self.master_token
                    return self.master_token

                error_detail = res.get("Error", "").lower()
                error_url = res.get("Url", "").lower()
                _LOGGER.debug("Google auth response details: %s", res)

                if (
                    "advancedprotection" in error_detail
                    or "advancedprotection" in error_url
                    or "securesignin" in error_detail
                ):
                    raise AdvancedProtectionActive(
                        "Google Advanced Protection Program blocks password/app-password authentication."
                    )

                if (
                    "needsbrowser" in error_detail
                    or "secondfactor" in error_detail
                    or "badauthentication" in error_detail
                ):
                    raise TwoFactorRequired(
                        f"Google 2FA / App Password required ({res.get('Error')})"
                    )
            except (AuthenticationFailed, TwoFactorRequired, AdvancedProtectionActive):
                raise
            except Exception as err:
                _LOGGER.debug("Direct master login exception: %s", err)

            return self._client.get_master_token()

        try:
            master_token = await self.hass.async_add_executor_job(_get_master_token)
        except (TwoFactorRequired, AdvancedProtectionActive):
            raise
        except Exception as err:
            raise AuthenticationFailed(f"Failed to fetch master token: {err}") from err

        if master_token is None:
            raise TwoFactorRequired(
                "Could not obtain master token, App Password / 2FA required"
            )
        self.master_token = master_token
        return master_token

    async def exchange_web_token(self, oauth_token: str) -> str:
        """Exchange browser oauth_token (from accounts.google.com/EmbeddedSetup) for master token."""
        username = self.username
        if not username:
            raise AuthenticationFailed(
                "Email username is required to exchange web oauth token."
            )

        def _exchange() -> str | None:
            from gpsoauth import exchange_token

            res = exchange_token(
                username,
                oauth_token,
                self._client.get_android_id(),
            )
            _LOGGER.debug(
                "OAuth token exchange response: %s",
                {k: v for k, v in res.items() if k != "Token"},
            )
            if "Token" in res:
                return res["Token"]
            return None

        try:
            token = await self.hass.async_add_executor_job(_exchange)
        except Exception as err:
            raise AuthenticationFailed(
                f"Failed to exchange web oauth token: {err}"
            ) from err

        if not token:
            raise InvalidMasterToken("Google rejected the OAuth token exchange.")
        self.master_token = token
        self._client.master_token = token
        return token

    async def get_access_token(self) -> str:
        """Get Google access token using master token."""
        if not self.master_token:
            await self.get_master_token()

        def _get_access_token() -> str | None:
            return self._client.get_access_token()

        try:
            access_token = await self.hass.async_add_executor_job(_get_access_token)
        except Exception as err:
            raise AuthenticationFailed(f"Failed to fetch access token: {err}") from err

        if access_token is None:
            raise InvalidMasterToken("Could not obtain access token")
        return access_token

    async def get_google_devices(
        self, force_reload: bool = False
    ) -> list[GoogleHomeDevice]:
        """Get google device authentication tokens and discovered IP addresses."""
        if not self.google_devices or force_reload:
            # Check and validate access token upfront so expired master token raises AuthenticationFailed
            await self.get_access_token()

            def _get_google_devices() -> list[Device]:
                devices = self._client.get_google_devices(
                    zeroconf_instance=self.zeroconf_instance,
                    force_homegraph_reload=force_reload,
                )
                # glocaltokens matches the advertised `cd` to agent_info.unique_id.
                # Keep that identity even when its initial network scan missed a device.
                homegraph = self._client.get_homegraph()
                if homegraph is not None:
                    self._discovery_ids = {
                        item.device_info.device_id: item.device_info.agent_info.unique_id
                        for item in homegraph.home.devices
                        if item.device_info.agent_info.unique_id
                    }
                return devices

            google_devices = await self.hass.async_add_executor_job(_get_google_devices)

            # Update or create device list while preserving existing states
            available_homes = await self.async_get_available_homes()
            existing_by_id = {d.device_id: d for d in self.google_devices}
            new_devices: list[GoogleHomeDevice] = []
            for device in google_devices:
                # Skip non-compatible cast or router devices with missing or malformed tokens (Fixes Issue #932)
                if not getattr(device, "local_auth_token", None):
                    _LOGGER.debug(
                        "Skipping device %s (no local auth token available)",
                        getattr(device, "device_name", "Unknown"),
                    )
                    continue

                # Determine structure ID and name for this device by checking device name and HomeGraph correlation
                dev_structure_id = None
                dev_structure_name = None
                raw_dev_bytes = str(getattr(device, "device_name", "")).encode()

                for hid, hname in available_homes.items():
                    if hid.encode() in raw_dev_bytes or hname.encode() in raw_dev_bytes:
                        dev_structure_id = hid
                        dev_structure_name = hname
                        break

                if not dev_structure_id and available_homes:
                    # Check if device belongs to another structure by scanning raw HomeGraph
                    try:
                        hg = self._client.get_homegraph()
                        if hg and hasattr(hg, "home"):
                            for r in getattr(hg.home, "rooms", []):
                                r_bytes = r.SerializeToString()
                                if (
                                    getattr(device, "device_id", "").encode() in r_bytes
                                    or raw_dev_bytes in r_bytes
                                ):
                                    rid = getattr(r, "room_id", "")
                                    if "." in rid:
                                        p_uuid = rid.split(".")[0]
                                        if p_uuid in available_homes:
                                            dev_structure_id = p_uuid
                                            dev_structure_name = available_homes[p_uuid]
                                            break
                    except Exception:
                        pass

                if not dev_structure_id and available_homes:
                    first_hid = next(iter(available_homes))
                    dev_structure_id = first_hid
                    dev_structure_name = available_homes[first_hid]

                # Filter by selected_homes if specified (allow match by structure ID or structure name)
                if self.selected_homes and not (
                    dev_structure_id in self.selected_homes
                    or dev_structure_name in self.selected_homes
                ):
                    _LOGGER.debug(
                        "Skipping local speaker %s because its home %s (%s) is not in selected_homes: %s",
                        getattr(device, "device_name", ""),
                        dev_structure_name,
                        dev_structure_id,
                        self.selected_homes,
                    )
                    continue

                dev_ip = getattr(device, "ip_address", None) or (
                    getattr(device.network_device, "ip_address", None)
                    if getattr(device, "network_device", None)
                    else None
                )

                matched_cast_uuid = None
                if self.hass:
                    from homeassistant.helpers import (
                        device_registry as dr,
                    )
                    from homeassistant.helpers import (
                        entity_registry as er,
                    )

                    ent_reg = er.async_get(self.hass)
                    dev_reg = dr.async_get(self.hass)

                    dname = str(getattr(device, "device_name", "")).strip().lower()
                    slug = dname.replace(" ", "_")

                    # 1. First pass: look through media_player states for matching name or IP
                    for state in self.hass.states.async_all("media_player"):
                        fname = (
                            state.attributes.get("friendly_name", "").strip().lower()
                        )
                        state_ip = (
                            state.attributes.get("ip_address")
                            or state.attributes.get("ip")
                            or state.attributes.get("host")
                        )
                        ip_matches = bool(
                            dev_ip and state_ip and str(state_ip) == str(dev_ip)
                        )
                        name_matches = bool(
                            fname == dname or (slug and slug in state.entity_id)
                        )

                        if ip_matches or name_matches:
                            if not dev_ip and state_ip:
                                dev_ip = str(state_ip)

                            ent_entry = ent_reg.async_get(state.entity_id)
                            if ent_entry and ent_entry.device_id:
                                ha_dev = dev_reg.async_get(ent_entry.device_id)
                                if ha_dev:
                                    for identifier in ha_dev.identifiers:
                                        if (
                                            len(identifier) >= 2
                                            and identifier[0] == "cast"
                                        ):
                                            matched_cast_uuid = (
                                                str(identifier[1])
                                                .replace("-", "")
                                                .strip()
                                            )
                                            break

                        if dev_ip and matched_cast_uuid:
                            break

                    # 2. Second pass: search device registry directly for Cast devices by name if not found yet
                    if not matched_cast_uuid:
                        for d in dev_reg.devices:
                            cast_id = None
                            for identifier in d.identifiers:
                                if len(identifier) >= 2 and identifier[0] == "cast":
                                    cast_id = (
                                        str(identifier[1]).replace("-", "").strip()
                                    )
                                    break
                            if cast_id:
                                dev_name = (
                                    (d.name_by_user or d.name or "").strip().lower()
                                )
                                if dev_name == dname:
                                    matched_cast_uuid = cast_id
                                    break

                    # 3. Third pass: check other state entities for dev_ip fallback
                    if not dev_ip:
                        for state in self.hass.states.async_all():
                            fname = (
                                state.attributes.get("friendly_name", "")
                                .strip()
                                .lower()
                            )
                            if fname == dname or (slug and slug in state.entity_id):
                                ip_cand = (
                                    state.attributes.get("ip_address")
                                    or state.attributes.get("ip")
                                    or state.attributes.get("host")
                                )
                                if ip_cand:
                                    dev_ip = str(ip_cand)
                                    break

                if device.device_id in existing_by_id:
                    dev = existing_by_id[device.device_id]
                    dev.name = device.device_name
                    dev.auth_token = device.local_auth_token
                    if dev_ip:
                        dev.ip_address = dev_ip
                    if matched_cast_uuid and not getattr(dev, "cast_uuid", None):
                        dev.cast_uuid = matched_cast_uuid
                    dev.hardware = device.hardware
                    dev.structure_id = dev_structure_id
                    dev.structure_name = dev_structure_name
                    new_devices.append(dev)
                else:
                    new_dev = GoogleHomeDevice(
                        device_id=device.device_id,
                        name=device.device_name,
                        auth_token=device.local_auth_token,
                        ip_address=dev_ip,
                        hardware=device.hardware,
                        structure_id=dev_structure_id,
                        structure_name=dev_structure_name,
                    )
                    if matched_cast_uuid:
                        new_dev.cast_uuid = matched_cast_uuid
                    new_devices.append(new_dev)
            self.google_devices = new_devices
            _LOGGER.debug(
                "Discovered %d compatible Google Home devices: %s",
                len(self.google_devices),
                [f"{d.name} ({d.ip_address})" for d in self.google_devices],
            )

        await self._async_resolve_missing_addresses(self.google_devices)
        return self.google_devices

    async def _async_resolve_missing_addresses(
        self, devices: list[GoogleHomeDevice]
    ) -> None:
        """Retry missing addresses locally, with identity checks and one shared scan."""
        if not self.zeroconf_instance or all(device.ip_address for device in devices):
            return
        async with self._address_discovery_lock:
            missing = [device for device in devices if not device.ip_address]
            if not missing:
                return
            now = self.hass.loop.time()
            if (
                self._last_address_discovery is not None
                and now - self._last_address_discovery < 30
            ):
                return
            self._last_address_discovery = now
            try:
                addresses = await self.hass.async_add_executor_job(
                    discover_cast_addresses, self.zeroconf_instance
                )
            except (OSError, RuntimeError) as err:
                _LOGGER.debug("Local address discovery failed: %s", err, exc_info=True)
                return

            from homeassistant.helpers import device_registry as dr

            registry = dr.async_get(self.hass)
            for device in missing:
                # Use the exact Google Home identifier; names and zero MACs cannot
                # safely identify a receiver after a legacy device merge.
                cast_ids = {
                    cast_id
                    for entry in registry.devices
                    if (DOMAIN, device.device_id) in entry.identifiers
                    for domain, value in entry.identifiers
                    if domain == "cast" and (cast_id := normalize_cast_uuid(value))
                }
                if cast_id := normalize_cast_uuid(device.cast_uuid):
                    cast_ids.add(cast_id)
                if len(cast_ids) > 1:
                    _LOGGER.debug("Ambiguous Cast identity for %s", device.name)
                    continue
                discovery_id = self._discovery_ids.get(device.device_id)
                matches = {
                    address
                    for address in addresses
                    if (
                        (discovery_id and address.discovery_id == discovery_id)
                        or address.cast_uuid in cast_ids
                    )
                    and (
                        not cast_ids
                        or address.cast_uuid is None
                        or address.cast_uuid in cast_ids
                    )
                }
                if len(matches) == 1:
                    address = next(iter(matches))
                    device.ip_address = address.host
                    if address.cast_uuid:
                        device.cast_uuid = address.cast_uuid
                    _LOGGER.debug("Recovered local address for %s", device.name)
                else:
                    _LOGGER.debug(
                        "No unambiguous local address for %s (%d announcements, %d matches)",
                        device.name,
                        len(addresses),
                        len(matches),
                    )

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
                        rssi_int = int(round(float(raw_rssi)))
                    except (ValueError, TypeError):
                        pass

                device.set_wifi_info(
                    ssid=str(raw_ssid) if raw_ssid is not None else None,
                    rssi=rssi_int,
                )

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
                # Extract OTA status if reported by device
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

                fw_str = str(firmware) if firmware else None

                device.set_system_info(
                    firmware=fw_str,
                    cast_firmware=cast_firmware,
                    system_firmware=system_firmware,
                    mac=str(net_mac) if net_mac else None,
                    cast_uuid=cast_uuid if cast_uuid else None,
                    ota_status=str(ota_status) if ota_status else None,
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
