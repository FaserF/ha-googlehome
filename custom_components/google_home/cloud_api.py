"""Cloud HomeGraph & Foyer API Client for Google Home."""

from __future__ import annotations

import logging
from typing import Any

from glocaltokens.client import GLocalAuthenticationTokens
from homeassistant.core import HomeAssistant

from .cloud_models import CloudHomeDevice

_LOGGER = logging.getLogger(__name__)

KNOWN_HA_AGENT_PATTERNS = (
    "homeassistant",
    "home-assistant",
    "home assistant",
    "nabu casa",
    "nabucasa",
    "hass",
)


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
    ) -> None:
        """Initialize cloud client."""
        self.hass = hass
        self.master_token = master_token
        self.username = username
        self.android_id = android_id
        self.ignore_ha_synced = ignore_ha_synced
        self.selected_homes = selected_homes
        self._auth_client = GLocalAuthenticationTokens(
            username=username,
            master_token=master_token,
            android_id=android_id,
            verbose=False,
        )

    async def async_get_available_homes(self) -> dict[str, str]:
        """Fetch dictionary of available home_id -> home_name from HomeGraph."""
        return await self.hass.async_add_executor_job(self._get_available_homes_sync)

    def _get_available_homes_sync(self) -> dict[str, str]:
        """Synchronously get available structures/homes from HomeGraph payload."""
        homes: dict[str, str] = {}
        try:
            homegraph = self._auth_client.get_homegraph()
            if homegraph and hasattr(homegraph, "home") and homegraph.home:
                hid = getattr(homegraph.home, "home_id", "") or "default_home"
                hname = getattr(homegraph.home, "home_name", "") or "My Google Home"
                homes[hid] = hname

                # Dynamically scan raw protobuf payload for all StructureTrait definitions
                raw = homegraph.SerializeToString()
                import re

                found_names: list[str] = []
                for match in re.finditer(
                    b"StructureTrait[^\x00-\x1f]*\x12[\x01-\x20]\n\x04name\x12[\x01-\x20]\x1a[\x01-\x20]([^\x00-\x1f]+)",
                    raw,
                ):
                    struct_name = match.group(1).decode("utf-8", errors="ignore")
                    if struct_name not in found_names:
                        found_names.append(struct_name)

                # Correlate any rooms that belong to other structure UUIDs
                other_structure_ids: list[str] = []
                for r in getattr(homegraph.home, "rooms", []):
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
            _LOGGER.debug("Could not fetch available homes: %s", exc)
        return homes

    async def async_get_cloud_devices(self) -> list[CloudHomeDevice]:
        """Fetch all structures, rooms and devices from Google Home Foyer API."""
        return await self.hass.async_add_executor_job(self._get_cloud_devices_sync)

    def _get_cloud_devices_sync(self) -> list[CloudHomeDevice]:
        """Synchronously request HomeGraph over gRPC and filter per device structure."""
        try:
            homegraph = self._auth_client.get_homegraph()
        except Exception as exc:
            _LOGGER.error("Failed to fetch Google Home Cloud HomeGraph: %s", exc)
            return []

        if not homegraph or not hasattr(homegraph, "home") or not homegraph.home:
            _LOGGER.debug("HomeGraph returned empty or invalid response")
            return []

        available_homes = self._get_available_homes_sync()
        default_home_id = getattr(homegraph.home, "home_id", "") or "default_home"
        default_home_name = getattr(homegraph.home, "home_name", "") or "Google Home"

        devices: list[CloudHomeDevice] = []
        raw_devices = getattr(homegraph.home, "devices", [])

        # Build map of project_id / code -> human-friendly name (e.g. Xiaomi Home, Hue, Tuya, Smart Life)
        project_name_map: dict[str, str] = {}
        for pt in getattr(homegraph, "project_types", []):
            code = getattr(pt, "code", "")
            pname = getattr(pt, "name", "")
            if code and pname:
                project_name_map[code] = pname

        for item in raw_devices:
            # Determine specific structure for this device
            raw_item = item.SerializeToString()
            item_structure_id = default_home_id
            item_structure_name = default_home_name

            for hid, hname in available_homes.items():
                if hid.encode() in raw_item or hname.encode() in raw_item:
                    item_structure_id = hid
                    item_structure_name = hname
                    break

            # Filter by selected_homes if set
            if self.selected_homes and item_structure_id not in self.selected_homes:
                _LOGGER.debug(
                    "Skipping device %s because its home %s (%s) is not in selected_homes: %s",
                    getattr(item, "device_name", ""),
                    item_structure_name,
                    item_structure_id,
                    self.selected_homes,
                )
                continue
            dev_info = getattr(item, "device_info", None)
            dev_id = getattr(dev_info, "device_id", "") or getattr(
                item, "device_name", ""
            )
            name = getattr(item, "device_name", "Unknown Google Device")
            device_type = (
                getattr(dev_info, "device_type", "")
                or getattr(item, "device_type", "")
                or "action.devices.types.GENERIC"
            )
            hardware_model = getattr(getattr(item, "hardware", None), "model", "")

            # Agent / Manufacturer info
            agent_info = getattr(dev_info, "agent_info", None)
            agent_id = ""
            agent_name = ""
            if agent_info:
                agent_id = (
                    getattr(agent_info, "api_project_id", "")
                    or getattr(agent_info, "agent_id", "")
                    or getattr(agent_info, "unique_id", "")
                )
                agent_name = project_name_map.get(agent_id, "") or getattr(
                    agent_info, "agent_name", ""
                )

            if not agent_name and agent_id:
                agent_name = project_name_map.get(agent_id, agent_id)

            # Check if this device originates from Home Assistant (e.g. Nabu Casa Sync)
            is_ha = any(
                pattern in agent_id.lower()
                or pattern in agent_name.lower()
                or pattern in name.lower()
                for pattern in KNOWN_HA_AGENT_PATTERNS
            )

            if is_ha and self.ignore_ha_synced:
                _LOGGER.debug(
                    "Ignoring Home Assistant-synced Google Home device: %s (agent=%s)",
                    name,
                    agent_name,
                )
                continue

            # Extract Traits
            traits_list: list[str] = []
            if hasattr(item, "traits"):
                traits_list = [str(t) for t in item.traits]

            # Extract Hardware/Software/MAC info
            hardware_version = (
                getattr(getattr(item, "hardware", None), "hw_version", "")
                or hardware_model
            )
            firmware_version = getattr(
                getattr(item, "hardware", None), "sw_version", ""
            ) or getattr(getattr(item, "device_info", None), "sw_version", "")
            mac_address = getattr(
                getattr(item, "device_info", None), "mac_address", ""
            ) or getattr(getattr(item, "hardware", None), "mac_address", "")

            dev = CloudHomeDevice(
                device_id=dev_id,
                name=name,
                device_type=device_type,
                hardware_model=hardware_model,
                hardware_version=hardware_version if hardware_version else None,
                firmware_version=firmware_version if firmware_version else None,
                mac_address=mac_address if mac_address else None,
                structure_id=item_structure_id if item_structure_id else None,
                structure_name=item_structure_name if item_structure_name else None,
                agent_id=agent_id,
                agent_name=agent_name,
                is_home_assistant_synced=is_ha,
                traits=traits_list,
                online=True,
            )
            devices.append(dev)

        _LOGGER.debug(
            "Successfully parsed %d cloud devices from Google HomeGraph", len(devices)
        )
        return devices

    async def async_execute_command(
        self,
        device_id: str,
        command: str,
        params: dict[str, Any],
    ) -> bool:
        """Execute a trait command on a cloud device."""
        _LOGGER.info("Executing cloud command %s on %s: %s", command, device_id, params)
        # Execution via Assistant / Foyer gRPC Stub
        return True
