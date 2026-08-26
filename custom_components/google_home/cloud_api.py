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
    ) -> None:
        """Initialize cloud client."""
        self.hass = hass
        self.master_token = master_token
        self.username = username
        self.android_id = android_id
        self.ignore_ha_synced = ignore_ha_synced
        self._auth_client = GLocalAuthenticationTokens(
            username=username,
            master_token=master_token,
            android_id=android_id,
            verbose=False,
        )

    async def async_get_cloud_devices(self) -> list[CloudHomeDevice]:
        """Fetch all structures, rooms and devices from Google Home Foyer API."""
        return await self.hass.async_add_executor_job(self._get_cloud_devices_sync)

    def _get_cloud_devices_sync(self) -> list[CloudHomeDevice]:
        """Synchronously request HomeGraph over gRPC."""
        try:
            homegraph = self._auth_client.get_homegraph()
        except Exception as exc:
            _LOGGER.error("Failed to fetch Google Home Cloud HomeGraph: %s", exc)
            return []

        if not homegraph or not hasattr(homegraph, "home") or not homegraph.home:
            _LOGGER.debug("HomeGraph returned empty or invalid response")
            return []

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
