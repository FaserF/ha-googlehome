"""Device discovery and address recovery mixin for Google Home API client."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp
from glocaltokens.client import Device, GLocalAuthenticationTokens

from ..const import API_ENDPOINT_DEVICE_INFO, DOMAIN
from ..local_discovery import discover_cast_addresses, normalize_cast_uuid
from ..models import GoogleHomeDevice

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from zeroconf import Zeroconf

_LOGGER: logging.Logger = logging.getLogger(__package__)


class DiscoveryMixin:
    """Mixin handling device discovery, zeroconf address resolution and known hosts."""

    hass: HomeAssistant
    _session: aiohttp.ClientSession
    zeroconf_instance: Zeroconf | None
    selected_homes: list[str] | None
    known_hosts: list[str]
    google_devices: list[GoogleHomeDevice]
    _discovery_ids: dict[str, str]
    _address_discovery_lock: asyncio.Lock
    _last_address_discovery: float | None
    _client: GLocalAuthenticationTokens

    async def get_access_token(self) -> str:
        """Declared for type checkers; implemented in AuthMixin."""
        raise NotImplementedError

    async def async_get_available_homes(self) -> dict[str, str]:
        """Declared for type checkers; implemented in AuthMixin."""
        raise NotImplementedError

    def create_url(self, ip_address: str, endpoint: str) -> str:
        """Declared for type checkers; implemented in OperationsMixin."""
        raise NotImplementedError

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

            # Check known hosts for devices still missing an IP address
            unresolved = [d for d in self.google_devices if not d.ip_address]
            if unresolved and self.known_hosts:
                assigned = {d.ip_address for d in self.google_devices if d.ip_address}
                candidates = [h for h in self.known_hosts if h not in assigned]
                for host in candidates:
                    try:
                        url = self.create_url(host, API_ENDPOINT_DEVICE_INFO)
                        async with self._session.get(
                            url, timeout=aiohttp.ClientTimeout(total=4)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if isinstance(data, dict):
                                    dev_info = data.get("device_info") or {}
                                    cloud_id = dev_info.get(
                                        "cloud_device_id"
                                    ) or data.get("cloud_device_id")
                                    name = data.get("name")
                                    for udev in unresolved:
                                        if (
                                            cloud_id
                                            and str(cloud_id).lower()
                                            == udev.device_id.lower()
                                        ) or (
                                            name
                                            and str(name).lower() == udev.name.lower()
                                        ):
                                            udev.ip_address = host
                                            _LOGGER.debug(
                                                "Found %s at known host %s",
                                                udev.name,
                                                host,
                                            )
                                            break
                    except Exception as exc:
                        _LOGGER.debug("Known host %s check error: %s", host, exc)
