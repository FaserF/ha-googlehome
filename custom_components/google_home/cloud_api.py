"""Cloud HomeGraph & Foyer API Client for Google Home."""

from __future__ import annotations

import logging
from typing import Any

from glocaltokens.client import GLocalAuthenticationTokens
from homeassistant.core import HomeAssistant

from .cloud_models import CloudHomeDevice
from .cloud_parser import (
    get_project_names,
    get_service_info,
    parse_cloud_devices,
)
from .exceptions import AuthenticationFailed

_LOGGER = logging.getLogger(__name__)


class GoogleHomeCloudClient:
    """Client for Google Home Cloud (HomeGraph & Foyer V2 gRPC API)."""

    def __init__(
        self,
        hass: HomeAssistant,
        master_token: str,
        username: str | None = None,
        android_id: str | None = None,
        ignore_ha_synced: bool = True,
        selected_homes: list[str] | None = None,
        excluded_services: list[str] | None = None,
    ) -> None:
        """Initialize cloud client."""
        self.hass = hass
        self.master_token = master_token
        self.username = username
        self.android_id = android_id
        self.ignore_ha_synced = ignore_ha_synced
        self.selected_homes = selected_homes
        self.excluded_services = set(excluded_services or ())
        self.excluded_device_ids: set[str] = set()
        self._auth_client = GLocalAuthenticationTokens(
            username=username,
            master_token=master_token,
            android_id=android_id,
            verbose=False,
        )
        # Populated by _get_available_homes_sync; maps short/prefix UUID → canonical 64-char hex
        self._structure_alias_map: dict[str, str] = {}
        self._cached_homes: dict[str, str] = {}

    _get_service_info = staticmethod(get_service_info)

    _get_project_names = staticmethod(get_project_names)

    async def async_get_available_services(self) -> dict[str, str]:
        """Discover linked services, including services currently excluded."""
        return await self.hass.async_add_executor_job(self._get_available_services_sync)

    def _get_available_services_sync(self) -> dict[str, str]:
        """Read provider metadata from the unfiltered HomeGraph."""
        homegraph = self._auth_client.get_homegraph()
        project_names = self._get_project_names(homegraph)
        services: dict[str, str] = {}
        for item in getattr(getattr(homegraph, "home", None), "devices", []):
            service_id, service_name = self._get_service_info(item, project_names)
            if service_id:
                services[service_id] = service_name
        return services

    async def async_get_available_homes(self) -> dict[str, str]:
        """Fetch dictionary of available home_id -> home_name from HomeGraph."""
        if self._cached_homes:
            return self._cached_homes
        homes = await self.hass.async_add_executor_job(self._get_available_homes_sync)
        if homes:
            self._cached_homes = homes
        return homes

    def _get_available_homes_sync(self) -> dict[str, str]:
        """Synchronously get available structures/homes from HomeGraph payload."""
        homes: dict[str, str] = {}
        try:
            homegraph = self._auth_client.get_homegraph()
            if homegraph and hasattr(homegraph, "home") and homegraph.home:
                hid = getattr(homegraph.home, "home_id", "") or "default_home"
                hname = getattr(homegraph.home, "home_name", "") or "My Google Home"
                homes[hid] = hname

                raw = homegraph.SerializeToString()
                import re

                # --- Step 1: collect distinct prefix UUIDs from room_ids ---
                # room_id format: "{prefix_uuid}.{room_uuid}"
                # The prefix_uuid is the canonical structure identifier used in
                # room → device mappings.  We collect them in insertion order.
                prefix_uuids: list[str] = []
                prefix_to_room_bytes: dict[str, list[bytes]] = {}
                for r in getattr(homegraph.home, "rooms", []):
                    rid = getattr(r, "room_id", "")
                    if "." in rid:
                        p = rid.split(".")[0]
                        if p not in prefix_to_room_bytes:
                            prefix_uuids.append(p)
                            prefix_to_room_bytes[p] = []
                        prefix_to_room_bytes[p].append(r.SerializeToString())

                # --- Step 2: match StructureTrait names to prefix UUIDs ---
                # Each room's serialized bytes contain its structure name
                # (via StructureTrait embedded in the protobuf blob).
                struct_name_re = re.compile(
                    rb"StructureTrait[^\x00-\x1F]*\x12[\x01-\x20]\n\x04name\x12[\x01-\x20]\x1a[\x01-\x20]([^\x00-\x1F]+)"
                )

                prefix_to_name: dict[str, str] = {}
                # Search each room's bytes for a StructureTrait name
                for p, room_bytes_list in prefix_to_room_bytes.items():
                    for rb in room_bytes_list:
                        m = struct_name_re.search(rb)
                        if m:
                            sname = m.group(1).decode("utf-8", errors="ignore").strip()
                            if sname:
                                prefix_to_name[p] = sname
                                break

                # Fallback: search full raw payload for StructureTrait names
                # and pair by order with ordered prefix_uuids list
                if len(prefix_to_name) < len(prefix_uuids):
                    all_names: list[str] = []
                    for match in struct_name_re.finditer(raw):
                        sname = match.group(1).decode("utf-8", errors="ignore").strip()
                        if sname and sname != hname and sname not in all_names:
                            all_names.append(sname)
                    for idx, p in enumerate(prefix_uuids):
                        if p not in prefix_to_name and idx < len(all_names):
                            prefix_to_name[p] = all_names[idx]

                # --- Step 3: find 64-char hex IDs for each prefix UUID ---
                # The 64-char hex for a structure appears in the raw bytes near
                # or alongside the prefix UUID bytes.
                hex64_re = re.compile(rb"[0-9a-fA-F]{64}")
                all_hex64: list[tuple[int, str]] = [
                    (m.start(), m.group(0).decode()) for m in hex64_re.finditer(raw)
                ]

                prefix_to_hex64: dict[str, str] = {}
                for p in prefix_uuids:
                    p_bytes = p.encode()
                    # Find positions of this prefix UUID in raw
                    for pm in re.finditer(re.escape(p_bytes), raw):
                        pm_pos = pm.start()
                        # Closest 64-char hex within 4096 bytes
                        best: tuple[int, str] | None = None
                        best_dist = 99999999
                        for hpos, hval in all_hex64:
                            dist = abs(hpos - pm_pos)
                            if dist < best_dist and dist < 4096:
                                best_dist = dist
                                best = (hpos, hval)
                        if best:
                            prefix_to_hex64[p] = best[1]
                            break

                # Build the homes dict: canonical 64-char hex → structure name
                # (also keep hid → hname for the primary home)
                for p in prefix_uuids:
                    sname = prefix_to_name.get(p)
                    if not sname:
                        continue
                    hex64 = prefix_to_hex64.get(p)
                    if hex64:
                        homes[hex64] = sname
                        _LOGGER.debug(
                            "Structure '%s' → hex %s... (via prefix %s...)",
                            sname,
                            hex64[:8],
                            p[:8],
                        )
                    else:
                        # No 64-char hex found; use prefix UUID as key
                        homes[p] = sname
                        _LOGGER.debug(
                            "Structure '%s' → prefix %s... (no 64-char hex found)",
                            sname,
                            p[:8],
                        )

                # Build alias map: prefix UUID → canonical key (64-char or prefix)
                self._structure_alias_map = {}
                for p in prefix_uuids:
                    hex64 = prefix_to_hex64.get(p)
                    canonical = hex64 if hex64 and hex64 in homes else p
                    if canonical != p:
                        self._structure_alias_map[p] = canonical

                # Also alias short hid → canonical if name matches
                for sid, sname in list(homes.items()):
                    if len(sid) != 64 and sid not in self._structure_alias_map:
                        for hex64, hname64 in homes.items():
                            if len(hex64) == 64 and hname64 == sname and hex64 != sid:
                                self._structure_alias_map[sid] = hex64
                                break

                # Deduplicate: one entry per unique name (prefer 64-char hex key)
                name_to_canonical: dict[str, str] = {}
                for sid, sname in homes.items():
                    if sname not in name_to_canonical:
                        name_to_canonical[sname] = sid
                    elif len(sid) == 64 and len(name_to_canonical[sname]) != 64:
                        # Upgrade to 64-char key
                        old = name_to_canonical[sname]
                        name_to_canonical[sname] = sid
                        self._structure_alias_map[old] = sid

                deduped = {sid: sname for sname, sid in name_to_canonical.items()}
                if deduped:
                    self._cached_homes = deduped

                _LOGGER.debug(
                    "Available homes (deduped): %s",
                    {k[:8] + "...": v for k, v in deduped.items()},
                )
                return deduped

        except Exception as exc:
            _LOGGER.debug("Could not fetch available homes: %s", exc)
        if homes:
            self._cached_homes = homes
        return homes

    async def async_get_cloud_devices(self) -> list[CloudHomeDevice]:
        """Fetch all structures, rooms and devices from Google Home Foyer API."""
        return await self.hass.async_add_executor_job(self._get_cloud_devices_sync)

    def _get_cloud_devices_sync(self) -> list[CloudHomeDevice]:
        """Synchronously request HomeGraph over gRPC and filter per device structure."""
        try:
            homegraph = self._auth_client.get_homegraph()
        except Exception as exc:
            err_str = str(exc).lower()
            if any(
                k in err_str
                for k in (
                    "badauthentication",
                    "could not get access token",
                    "invalidmastertoken",
                    "unauthenticated",
                    "permission_denied",
                )
            ):
                raise AuthenticationFailed(
                    f"Authentication failed fetching HomeGraph: {exc}"
                ) from exc
            _LOGGER.error("Failed to fetch Google Home Cloud HomeGraph: %s", exc)
            return []

        if not homegraph or not hasattr(homegraph, "home") or not homegraph.home:
            # If homegraph is empty, verify if get_access_token failed
            if not self._auth_client.get_access_token():
                raise AuthenticationFailed(
                    "Could not obtain access token from master token"
                )
            _LOGGER.debug("HomeGraph returned empty or invalid response")
            return []

        available_homes = self._get_available_homes_sync()
        alias_map: dict[str, str] = getattr(self, "_structure_alias_map", {})
        project_name_map = self._get_project_names(homegraph)

        devices, excluded_device_ids = parse_cloud_devices(
            homegraph=homegraph,
            available_homes=available_homes,
            alias_map=alias_map,
            project_name_map=project_name_map,
            selected_homes=self.selected_homes,
            excluded_services=self.excluded_services,
            ignore_ha_synced=self.ignore_ha_synced,
        )
        self.excluded_device_ids = excluded_device_ids
        return devices

    async def async_execute_command(
        self,
        device_id: str,
        command: str,
        params: dict[str, Any],
    ) -> bool:
        """Execute a trait command on a cloud device.

        For third-party partner devices (Xiaomi, Tuya, Hue, Smart Life, etc.) the
        Google Foyer API does NOT expose an outbound execution endpoint for consumer
        accounts (returns 404 on /devices:exec and similar). Commands for those
        devices are silently dropped here to avoid user confusion from failed requests.

        Google-native devices (Cast speakers, Nest thermostats, Chromecast) are
        similarly not controllable via this path – their commands go through the local
        Cast / Nest API instead.
        """
        # Look up whether device is third-party
        device = self._get_device_from_cache(device_id)
        if device and device.is_third_party:
            _LOGGER.debug(
                "Skipping cloud command '%s' for third-party device '%s' (%s) – "
                "Google Foyer API does not support outbound execution for partner devices.",
                command,
                device.name,
                device_id,
            )
            return False

        # For Google-native devices also log that we attempted (currently no working endpoint)
        _LOGGER.debug(
            "Cloud command '%s' requested for device %s – "
            "no working Foyer execution endpoint available; skipping.",
            command,
            device_id,
        )
        return False

    def _get_device_from_cache(self, device_id: str) -> CloudHomeDevice | None:
        """Return a CloudHomeDevice from the last known coordinator data by device_id."""
        # Walk the hass states / coordinator cache – we store last fetched devices in
        # the coordinator; here we resolve via a simple linear scan over the
        # cached homegraph result if we have one.
        try:
            homegraph = self._auth_client.homegraph
            if not homegraph:
                return None
            raw_devices = getattr(getattr(homegraph, "home", None), "devices", [])
            for item in raw_devices:
                dev_info = getattr(item, "device_info", None)
                did = getattr(dev_info, "device_id", "") or getattr(
                    item, "device_name", ""
                )
                if did == device_id:
                    # Quick is_third_party check via agent_info
                    agent_info = getattr(dev_info, "agent_info", None)
                    agent_id = (
                        getattr(agent_info, "api_project_id", "")
                        or getattr(agent_info, "agent_id", "")
                        if agent_info
                        else ""
                    )
                    agent_name = (
                        getattr(agent_info, "agent_name", "") if agent_info else ""
                    )
                    from .cloud_models import CloudHomeDevice

                    stub = CloudHomeDevice(
                        device_id=did,
                        name=getattr(item, "device_name", ""),
                        device_type=getattr(dev_info, "device_type", "") or "",
                        agent_id=agent_id,
                        agent_name=agent_name,
                    )
                    return stub
        except Exception:
            pass
        return None
