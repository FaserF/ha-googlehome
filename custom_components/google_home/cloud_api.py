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
        # Populated by _get_available_homes_sync; maps short/prefix UUID → canonical 64-char hex
        self._structure_alias_map: dict[str, str] = {}
        self._cached_homes: dict[str, str] = {}

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
            _LOGGER.error("Failed to fetch Google Home Cloud HomeGraph: %s", exc)
            return []

        if not homegraph or not hasattr(homegraph, "home") or not homegraph.home:
            _LOGGER.debug("HomeGraph returned empty or invalid response")
            return []

        available_homes = self._get_available_homes_sync()
        # Alias map built during _get_available_homes_sync; short/prefix UUID → canonical 64-hex
        alias_map: dict[str, str] = getattr(self, "_structure_alias_map", {})
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

            item_structure_name = available_homes.get(
                item_structure_id, default_home_name
            )

            # Filter by selected_homes if set (allow match by structure ID or structure name)
            if self.selected_homes and not (
                item_structure_id in self.selected_homes
                or item_structure_name in self.selected_homes
            ):
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
                        state_dict["currentFanSpeedPercent"] = int(
                            fan_pct_match.group(1)
                        )
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
