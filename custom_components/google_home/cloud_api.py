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
                    rb"StructureTrait[^\x00-\x1F]*\x12[\x01-\x20]\n\x04name\x12[\x01-\x20]\x1a[\x01-\x20]([^\x00-\x1F]+)",
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

        # Build device_id -> (structure_id, room_name) lookup directly from HomeGraph rooms
        device_structure_map: dict[str, str] = {}
        device_room_map: dict[str, str] = {}

        for room in getattr(homegraph.home, "rooms", []):
            rid = getattr(room, "room_id", "") or getattr(room, "id", "")
            rname = getattr(room, "name", "") or getattr(room, "room_name", "")
            struct_id = rid.split(".")[0] if "." in rid else default_home_id
            r_bytes = room.SerializeToString()
            for r_dev in getattr(homegraph.home, "devices", []):
                r_dev_id = getattr(getattr(r_dev, "device_info", None), "device_id", "")
                if r_dev_id and r_dev_id.encode() in r_bytes:
                    device_structure_map[r_dev_id] = struct_id
                    if rname:
                        device_room_map[r_dev_id] = rname

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

            # Determine specific structure for this device (via room mapping first, then raw fallback)
            item_structure_id = device_structure_map.get(dev_id)
            if not item_structure_id:
                raw_item = item.SerializeToString()
                for hid in available_homes:
                    if hid.encode() in raw_item:
                        item_structure_id = hid
                        break

            # If still not matched, check if any room in HomeGraph contains this device
            if not item_structure_id:
                raw_item = item.SerializeToString()
                for r in getattr(homegraph.home, "rooms", []):
                    rid = getattr(r, "room_id", "")
                    r_bytes = r.SerializeToString()
                    if (
                        dev_id.encode() in r_bytes
                        or getattr(item, "device_name", "").encode() in r_bytes
                    ):
                        if "." in rid:
                            p_uuid = rid.split(".")[0]
                            if p_uuid in available_homes:
                                item_structure_id = p_uuid
                                break

            if not item_structure_id:
                # Default to primary structure only if not specifically configured
                item_structure_id = default_home_id

            item_structure_name = available_homes.get(
                item_structure_id, default_home_name
            )

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

            room_name = device_room_map.get(dev_id)

            # Fallback if not mapped via room
            if not room_name:
                raw_item = item.SerializeToString()
                for r in getattr(homegraph.home, "rooms", []):
                    r_name = getattr(r, "name", "") or getattr(r, "room_name", "")
                    if r_name and r_name.encode() in raw_item:
                        room_name = r_name
                        break

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

            # Extract Attributes & Capabilities from message20 (Key/Value pairs)
            attributes_dict: dict[str, Any] = {}
            m20 = getattr(item, "message20", None)
            if m20 and hasattr(m20, "message1"):
                for m_entry in m20.message1:
                    k = getattr(m_entry, "key", "")
                    if not k:
                        continue
                    # Extract capability flags and subkeys
                    raw_str = str(m_entry)
                    import re

                    extracted_values = re.findall(r'"([a-zA-Z0-9_\-\. ]+)"', raw_str)
                    clean_vals = [
                        v
                        for v in extracted_values
                        if v
                        not in ("key", "value", "message1", "message5", "message6", k)
                    ]
                    attributes_dict[k] = clean_vals if clean_vals else True

            # Extract State data from message30
            state_dict: dict[str, Any] = {}
            m30 = getattr(item, "message30", None)
            if m30:
                m30_str = str(m30)
                # Specific onOff parsing: extract exact boolean value
                import re

                # Match patterns like:
                # 1) key: "onOff" ... bool4: true / bool4: false
                # 2) "action.devices.traits.OnOff" ... bool4: true / false
                # 3) on: true / on: false
                on_match = re.search(
                    r"(?:onOff|action\.devices\.traits\.OnOff)[^}]*?bool4:\s*(true|false)",
                    m30_str,
                    re.IGNORECASE | re.DOTALL,
                )
                if on_match:
                    state_dict["on"] = on_match.group(1).lower() == "true"
                elif (
                    '"on": true' in m30_str
                    or '"on":true' in m30_str
                    or "on: true" in m30_str
                ):
                    state_dict["on"] = True
                elif (
                    '"on": false' in m30_str
                    or '"on":false' in m30_str
                    or "on: false" in m30_str
                ):
                    state_dict["on"] = False
                elif "bool4: false" in m30_str:
                    state_dict["on"] = False
                elif "bool4: true" in m30_str and 'string1: "online"' not in m30_str:
                    state_dict["on"] = True

                if "transportControl" in m30_str:
                    # Check if there is an explicit playing/playback state rather than just connectivity/static field
                    if "playbackState: 1" in m30_str or "playing" in m30_str.lower():
                        state_dict["activityState"] = "playing"
                    elif "paused" in m30_str.lower():
                        state_dict["activityState"] = "paused"

            dev = CloudHomeDevice(
                device_id=dev_id,
                name=name,
                device_type=device_type,
                hardware_model=hardware_model,
                hardware_version=hardware_version if hardware_version else None,
                firmware_version=firmware_version if firmware_version else None,
                mac_address=mac_address if mac_address else None,
                room_name=room_name,
                structure_id=item_structure_id if item_structure_id else None,
                structure_name=item_structure_name if item_structure_name else None,
                agent_id=agent_id,
                agent_name=agent_name,
                is_home_assistant_synced=is_ha,
                traits=traits_list,
                attributes=attributes_dict,
                state=state_dict,
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
