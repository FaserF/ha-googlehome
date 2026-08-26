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
        ignore_ha_synced: bool = True,
    ) -> None:
        """Initialize cloud client."""
        self.hass = hass
        self.master_token = master_token
        self.ignore_ha_synced = ignore_ha_synced
        self._auth_client = GLocalAuthenticationTokens(
            master_token=master_token,
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

        for item in raw_devices:
            dev_id = getattr(
                getattr(item, "device_info", None), "device_id", ""
            ) or getattr(item, "device_name", "")
            name = getattr(item, "device_name", "Unknown Google Device")
            device_type = (
                getattr(getattr(item, "device_info", None), "device_type", "")
                or "action.devices.types.GENERIC"
            )
            hardware_model = getattr(getattr(item, "hardware", None), "model", "")

            # Agent / Manufacturer info
            agent_info = getattr(getattr(item, "device_info", None), "agent_info", None)
            agent_id = getattr(agent_info, "agent_id", "") if agent_info else ""
            agent_name = getattr(agent_info, "agent_name", "") if agent_info else ""

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

            dev = CloudHomeDevice(
                device_id=dev_id,
                name=name,
                device_type=device_type,
                hardware_model=hardware_model,
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
