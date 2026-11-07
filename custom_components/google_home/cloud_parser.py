"""HomeGraph device parser and trait extractor for Google Home Cloud."""

from __future__ import annotations

import logging
import re
from typing import Any

from .cloud_models import CloudHomeDevice
from .const import clean_mac_address

_LOGGER = logging.getLogger(__name__)

KNOWN_HA_AGENT_PATTERNS = (
    "homeassistant",
    "home-assistant",
    "home assistant",
    "nabu casa",
    "nabucasa",
    "hass",
)


def get_service_info(item: Any, project_names: dict[str, str]) -> tuple[str, str]:
    """Read a device's linked service identity without relying on its name."""
    info = getattr(getattr(item, "device_info", None), "agent_info", None)
    service_id = (
        getattr(info, "api_project_id", "")
        or getattr(info, "agent_id", "")
        or getattr(info, "unique_id", "")
    )
    service_name = (
        project_names.get(service_id, "")
        or getattr(info, "agent_name", "")
        or service_id
    )
    return service_id, service_name


def get_project_names(homegraph: Any) -> dict[str, str]:
    """Map Google's linked service IDs to display names."""
    return {
        project.code: project.name
        for project in getattr(homegraph, "project_types", [])
        if getattr(project, "code", "") and getattr(project, "name", "")
    }


def parse_cloud_devices(
    homegraph: Any,
    available_homes: dict[str, str],
    alias_map: dict[str, str],
    project_name_map: dict[str, str],
    selected_homes: set[str] | list[str] | None = None,
    excluded_services: set[str] | list[str] | None = None,
    ignore_ha_synced: bool = False,
) -> tuple[list[CloudHomeDevice], set[str]]:
    """Parse HomeGraph devices into CloudHomeDevice models and collect excluded IDs."""
    default_home_id = getattr(homegraph.home, "home_id", "") or "default_home"
    default_home_name = getattr(homegraph.home, "home_name", "") or "Google Home"

    # Build device_id -> (structure_id, room_name) lookup directly from HomeGraph rooms
    device_structure_map: dict[str, str] = {}
    device_room_map: dict[str, str] = {}

    for room in getattr(homegraph.home, "rooms", []):
        rid = getattr(room, "room_id", "") or getattr(room, "id", "")
        rname = getattr(room, "name", "") or getattr(room, "room_name", "")
        raw_struct_id = rid.split(".")[0] if "." in rid else default_home_id
        # Resolve prefix UUID → canonical 64-char hex
        struct_id = alias_map.get(raw_struct_id, raw_struct_id)
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
    project_name_map = get_project_names(homegraph)
    excluded_device_ids: set[str] = set()

    for item in raw_devices:
        dev_info = getattr(item, "device_info", None)
        dev_id = getattr(dev_info, "device_id", "") or getattr(item, "device_name", "")

        # Determine specific structure for this device (via room mapping first, then raw fallback)
        item_structure_id = device_structure_map.get(dev_id)
        if not item_structure_id:
            raw_item = item.SerializeToString()
            # Prefer 64-char hex keys (canonical); sort by descending key length so
            # longer (canonical) keys are tried before short UUID aliases.
            for hid in sorted(available_homes, key=lambda k: -len(k)):
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
                        # Resolve prefix UUID → canonical via alias_map
                        resolved = alias_map.get(p_uuid, p_uuid)
                        if resolved in available_homes:
                            item_structure_id = resolved
                            break

        if not item_structure_id:
            # Resolve default home_id to canonical if possible
            item_structure_id = alias_map.get(default_home_id, default_home_id)

        item_structure_name = available_homes.get(item_structure_id, default_home_name)

        # Filter by selected_homes if set (allow match by structure ID or structure name)
        if selected_homes and not (
            item_structure_id in selected_homes or item_structure_name in selected_homes
        ):
            _LOGGER.debug(
                "Skipping device %s because its home %s (%s) is not in selected_homes: %s",
                getattr(item, "device_name", ""),
                item_structure_name,
                item_structure_id,
                selected_homes,
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
        agent_id, agent_name = get_service_info(item, project_name_map)
        if agent_id and excluded_services and agent_id in excluded_services:
            excluded_device_ids.add(dev_id)
            continue

        # Check if this device originates from Home Assistant (e.g. Nabu Casa Sync)
        is_ha = any(
            pattern in agent_id.lower()
            or pattern in agent_name.lower()
            or pattern in name.lower()
            for pattern in KNOWN_HA_AGENT_PATTERNS
        )

        if is_ha and ignore_ha_synced:
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
            getattr(getattr(item, "hardware", None), "hw_version", "") or hardware_model
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

                extracted_values = re.findall(r'"([a-zA-Z0-9_\-\. ]+)"', raw_str)
                clean_vals = [
                    v
                    for v in extracted_values
                    if v not in ("key", "value", "message1", "message5", "message6", k)
                ]
                attributes_dict[k] = clean_vals if clean_vals else True

        # Extract State data from message30
        state_dict: dict[str, Any] = {}
        m30 = getattr(item, "message30", None)
        if m30:
            m30_str = str(m30)
            # Specific onOff parsing: extract exact boolean value

            # Match patterns specifically for onOff / NightLight state:
            # 1) Specific NightLight trait
            nl_match = re.search(
                r"(?:action\.devices\.traits\.NightLight|nightLight)[^}]*?bool4:\s*(true|false)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if nl_match:
                nl_is_on = nl_match.group(1).lower() == "true"
                state_dict["nightlight_on"] = nl_is_on
            else:
                nl_bool_match = re.search(
                    r'"(?:nightLight|night_light)":\s*(true|false)',
                    m30_str,
                    re.IGNORECASE,
                )
                if nl_bool_match:
                    state_dict["nightlight_on"] = (
                        nl_bool_match.group(1).lower() == "true"
                    )
                else:
                    # If the device is a Smart Clock / Speaker, do NOT infer nightlight from general OnOff/Cast power!
                    # Only real dedicated lights (not speakers) may inherit nightlight_on from OnOff
                    if "action.devices.types.LIGHT" in device_type:
                        # Will be populated below if onOff is found
                        pass
                    else:
                        state_dict["nightlight_on"] = False

            # 2) Standard onOff trait in HomeGraph protobuf message30:
            on_match = re.search(
                r'(?:key:\s*"onOff"|action\.devices\.traits\.OnOff)[^}]*?bool4:\s*(true|false)',
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if on_match:
                is_on_val = on_match.group(1).lower() == "true"
                state_dict["on"] = is_on_val
                if (
                    "nightlight_on" not in state_dict
                    and "action.devices.types.LIGHT" in device_type
                ):
                    state_dict["nightlight_on"] = is_on_val
            else:
                # Exact JSON on field matches only (e.g. '"on": true' or '"on": false')
                json_on_match = re.search(
                    r'"on":\s*(true|false)', m30_str, re.IGNORECASE
                )
                if json_on_match:
                    json_is_on = json_on_match.group(1).lower() == "true"
                    state_dict["on"] = json_is_on
                    if (
                        "nightlight_on" not in state_dict
                        and "action.devices.traits.NightLight" in traits_list
                    ):
                        state_dict["nightlight_on"] = json_is_on
                else:
                    # Only default 'on' to False if device actually has the OnOff trait
                    if "action.devices.traits.OnOff" in traits_list:
                        state_dict["on"] = False
                    if "nightlight_on" not in state_dict:
                        state_dict["nightlight_on"] = False

            # Extract Brightness (0-100%)
            bri_match = re.search(
                r'(?:key:\s*"brightness"|action\.devices\.traits\.Brightness|brightness)[^}]*?(?:int\d+|val\d+|num\d+|value):\s*(\d+)',
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if bri_match:
                try:
                    state_dict["brightness"] = int(bri_match.group(1))
                except ValueError:
                    pass
            else:
                # Generic brightness pattern in proto dumps
                bri_gen = re.search(r'"brightness":\s*(\d+)', m30_str)
                if bri_gen:
                    try:
                        state_dict["brightness"] = int(bri_gen.group(1))
                    except ValueError:
                        pass

            # Extract Color (spectrumRGB)
            color_match = re.search(
                r"(?:spectrumRGB|spectrum_rgb|color)[^}]*?(?:int\d+|val\d+|num\d+|value):\s*(\d+)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if color_match:
                try:
                    state_dict["color"] = {"spectrumRGB": int(color_match.group(1))}
                except ValueError:
                    pass

            # Extract Cover OpenPercent (0-100%)
            open_pct_match = re.search(
                r"(?:openPercent|open_percent|openState)[^}]*?(?:int\d+|val\d+|num\d+|value):\s*(\d+)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if open_pct_match:
                try:
                    state_dict["openPercent"] = int(open_pct_match.group(1))
                except ValueError:
                    pass

            # Extract Fan Speed Percent / Fan Speed Setting
            fan_pct_match = re.search(
                r"(?:currentFanSpeedPercent|fanSpeedPercent)[^}]*?(?:int\d+|val\d+|num\d+|value):\s*(\d+)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if fan_pct_match:
                try:
                    state_dict["currentFanSpeedPercent"] = int(fan_pct_match.group(1))
                except ValueError:
                    pass

            # Extract Lock State
            lock_match = re.search(
                r"(?:isLocked|is_locked|isLockedState)[^}]*?bool4:\s*(true|false)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if lock_match:
                state_dict["isLocked"] = lock_match.group(1).lower() == "true"

            # Extract Vacuum State (isRunning / isDocked)
            if (
                "action.devices.types.VACUUM" in device_type
                or "mower" in device_type.lower()
            ):
                run_match = re.search(
                    r"(?:isRunning|is_running|cleaning)[^}]*?bool4:\s*(true|false)",
                    m30_str,
                    re.IGNORECASE | re.DOTALL,
                )
                if run_match:
                    state_dict["isRunning"] = run_match.group(1).lower() == "true"
                dock_match = re.search(
                    r"(?:isDocked|is_docked|docked)[^}]*?bool4:\s*(true|false)",
                    m30_str,
                    re.IGNORECASE | re.DOTALL,
                )
                if dock_match:
                    state_dict["isDocked"] = dock_match.group(1).lower() == "true"

            # Extract Thermostat Temperature & Setpoint
            amb_match = re.search(
                r"(?:thermostatTemperatureAmbient|temperatureAmbient)[^}]*?(?:int\d+|val\d+|num\d+|value|float\d+):\s*([0-9\.]+)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if amb_match:
                try:
                    state_dict["thermostatTemperatureAmbient"] = float(
                        amb_match.group(1)
                    )
                except ValueError:
                    pass
            set_match = re.search(
                r"(?:thermostatTemperatureSetpoint|temperatureSetpoint)[^}]*?(?:int\d+|val\d+|num\d+|value|float\d+):\s*([0-9\.]+)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if set_match:
                try:
                    state_dict["thermostatTemperatureSetpoint"] = float(
                        set_match.group(1)
                    )
                except ValueError:
                    pass

            # Extract Media Player / Speaker Volume (0-100%)
            vol_match = re.search(
                r"(?:currentVolume|volumeLevel|volume)[^}]*?(?:int\d+|val\d+|num\d+|value):\s*(\d+)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if vol_match:
                try:
                    state_dict["currentVolume"] = int(vol_match.group(1))
                    state_dict["volume"] = int(vol_match.group(1))
                except ValueError:
                    pass
            else:
                vol_gen = re.search(r'"(?:currentVolume|volume)":\s*(\d+)', m30_str)
                if vol_gen:
                    try:
                        state_dict["currentVolume"] = int(vol_gen.group(1))
                        state_dict["volume"] = int(vol_gen.group(1))
                    except ValueError:
                        pass

            # Extract Mute state
            mute_match = re.search(
                r"(?:isMuted|is_muted|mute)[^}]*?bool4:\s*(true|false)",
                m30_str,
                re.IGNORECASE | re.DOTALL,
            )
            if mute_match:
                state_dict["isMuted"] = mute_match.group(1).lower() == "true"

            # Extract Media playback / transport state
            pb_match = re.search(
                r'(?:playbackState|activityState|mediaState)[^}]*?(?:string\d+|val\d+|value):\s*"([^"]+)"',
                m30_str,
                re.IGNORECASE,
            )
            if pb_match:
                state_dict["activityState"] = pb_match.group(1).lower()
            else:
                pb_int_match = re.search(
                    r"(?:playbackState|activityState)[^}]*?(?:int\d+|val\d+|num\d+|value):\s*(\d+)",
                    m30_str,
                    re.IGNORECASE,
                )
                if pb_int_match:
                    val = pb_int_match.group(1)
                    # Google HomeGraph standard playback states: 1=PLAYING, 2=PAUSED, 3=STOPPED/STANDBY, 4=BUFFERING
                    if val == "1":
                        state_dict["activityState"] = "playing"
                    elif val == "2":
                        state_dict["activityState"] = "paused"
                    elif val == "3":
                        state_dict["activityState"] = "standby"
                    elif val == "4":
                        state_dict["activityState"] = "buffering"
                elif "transportControl" in m30_str or "mediaState" in m30_str:
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
            mac_address=clean_mac_address(mac_address),
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
    return devices, excluded_device_ids
