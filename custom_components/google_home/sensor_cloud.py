"""Cloud sensor entities for Google Home."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .cloud_models import CloudHomeDevice
from .const import DOMAIN, MANUFACTURER, clean_mac_address, get_structure_url

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeCloudBridgeSensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Home Cloud Bridge / Hub diagnostic sensor."""

    _attr_icon = "mdi:bridge"
    # Bridges are diagnostic only and disabled by default to reduce clutter
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        entry_id: str,
        device_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_bridge_status"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return f"{device.name} Status" if device else "Bridge Status"

    @property
    def native_value(self) -> str:
        """Return online status of bridge."""
        device = self.get_device()
        if not device:
            return "unavailable"
        return "online" if device.online else "offline"

    @property
    def available(self) -> bool:
        """Return availability."""
        device = self.get_device()
        return device is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return bridge diagnostic attributes."""
        device = self.get_device()
        if not device:
            return {}
        return {
            "bridge_name": device.name,
            "device_id": device.device_id,
            "device_type": device.device_type,
            "traits": device.traits,
            "agent_id": device.agent_id,
            "agent_name": device.agent_name,
            "hardware_model": device.hardware_model,
            "structure": device.structure_name,
            "room": device.room_name,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info grouping bridge sensor under its Google Home household main device."""
        device = self.get_device()
        struct_id = (
            device.structure_id if device and device.structure_id else "default_home"
        )
        struct_name = (
            device.structure_name if device and device.structure_name else "Google Home"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_structure_{struct_id}")},
            name=f"Google Home ({struct_name})",
            manufacturer=MANUFACTURER,
            model="Google Home Household & Structure",
            configuration_url=get_structure_url(
                device.structure_id if device else None, "devices"
            ),
        )


class GoogleHomeCloudStatusSensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Home Cloud status sensor.

    Always registered for all cloud devices (third-party and Google-native).
    In readonly mode for third-party devices: primary entity (no category).
    In control mode or for Google-native devices: supplemental diagnostic entity.
    """

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
        as_diagnostic: bool = False,
        enabled_by_default: bool = True,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_status"
        self._attr_entity_registry_enabled_default = enabled_by_default
        if as_diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return f"{device.name} Status" if device else "Google Device Status"

    @property
    def native_value(self) -> str:
        """Return human-readable device state. Never returns 'online'."""
        device = self.get_device()
        if not device:
            return "unavailable"
        return device.get_human_status()

    @property
    def icon(self) -> str:
        """Return dynamic icon based on device type and live state."""
        device = self.get_device()
        if not device:
            return "mdi:cloud-outline"
        val = str(self.native_value).lower()
        is_active = (
            val.startswith("on")
            or val
            in (
                "open",
                "playing",
                "cleaning",
                "running",
                "unlocked",
                "heat",
                "cool",
                "auto",
            )
            or "open (" in val
        )
        dtype = device.device_type.upper()

        if "LIGHT" in dtype:
            return "mdi:lightbulb-on" if is_active else "mdi:lightbulb-outline"
        if "SWITCH" in dtype or "OUTLET" in dtype or "PLUG" in dtype:
            return "mdi:power-socket-eu" if is_active else "mdi:power-socket-eu"
        if "FAN" in dtype or "AIRPURIFIER" in dtype:
            return "mdi:fan" if is_active else "mdi:fan-off"
        if "VACUUM" in dtype or "MOWER" in dtype:
            return (
                "mdi:robot-vacuum" if val == "cleaning" else "mdi:robot-vacuum-variant"
            )
        if "SHUTTER" in dtype or "BLINDS" in dtype or "CURTAIN" in dtype:
            return "mdi:window-shutter-open" if is_active else "mdi:window-shutter"
        if "LOCK" in dtype:
            return "mdi:lock-open-variant" if val == "unlocked" else "mdi:lock"
        if "TV" in dtype or "SETTOP" in dtype:
            return "mdi:television" if is_active else "mdi:television-off"
        if "SPEAKER" in dtype or "SOUNDBAR" in dtype:
            return "mdi:speaker-play" if val == "playing" else "mdi:speaker"
        if "THERMOSTAT" in dtype or "AC_UNIT" in dtype or "HEATER" in dtype:
            return "mdi:thermostat"
        if "CAMERA" in dtype or "DOORBELL" in dtype:
            return "mdi:camera"
        if "VALVE" in dtype or "SPRINKLER" in dtype or "FAUCET" in dtype:
            return "mdi:pipe-valve"
        if "GARAGE" in dtype:
            return "mdi:garage-open" if is_active else "mdi:garage"
        if "FRYER" in dtype or "COOKER" in dtype:
            return "mdi:pot-steam" if is_active else "mdi:pot"

        return "mdi:cloud-check" if is_active else "mdi:cloud-outline"

    @property
    def available(self) -> bool:
        """Return availability."""
        device = self.get_device()
        return device is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all state, network and diagnostic attributes."""
        device = self.get_device()
        if not device:
            return {}

        # Look up local speaker counterpart for network and Wi-Fi diagnostics if present
        local_ip: str | None = None
        wifi_ssid: str | None = None
        wifi_rssi: int | None = None
        bt_mac: str | None = None
        activity: str | None = None

        config_entry = getattr(self.coordinator, "config_entry", None)
        entry_id = getattr(config_entry, "entry_id", None) if config_entry else None
        if entry_id and entry_id in self.hass.data.get(DOMAIN, {}):
            local_coord = self.hass.data[DOMAIN][entry_id].get("coordinator")
            if local_coord:
                for ldev in local_coord.data or []:
                    if ldev.name.lower() == device.name.lower() or (
                        ldev.device_id and ldev.device_id == device.device_id
                    ):
                        local_ip = ldev.ip_address
                        wifi_ssid = ldev.get_wifi_ssid()
                        wifi_rssi = ldev.get_wifi_rssi()
                        bt_mac = ldev.get_bluetooth_mac()
                        activity = "idle" if ldev.available else "offline"
                        break

        attrs: dict[str, Any] = {
            "online": device.online,
            "device_type": device.device_type,
            "traits": device.traits,
            "agent_id": device.agent_id,
            "agent_name": device.agent_name,
            "hardware_model": device.hardware_model,
            "hardware_version": device.hardware_version,
            "firmware_version": device.firmware_version,
            "mac_address": device.mac_address,
            "bluetooth_mac": bt_mac,
            "device_ip": local_ip,
            "wifi_network": wifi_ssid,
            "wifi_signal_level": wifi_rssi,
            "activity": activity,
            "brightness": device.state.get("brightness"),
            "open_percent": device.state.get("openPercent"),
            "is_locked": device.state.get("isLocked"),
            "structure": device.structure_name,
            "room": device.room_name,
            "state_data": device.state,
            "attributes_data": device.attributes,
        }
        return {
            k: v
            for k, v in attrs.items()
            if v is not None and v != "" and v != [] and v != {}
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info."""
        device = self.get_device()
        connections = set()
        if device and device.mac_address:
            cleaned_mac = clean_mac_address(device.mac_address)
            if cleaned_mac:
                from homeassistant.helpers.device_registry import (
                    CONNECTION_NETWORK_MAC,
                    format_mac,
                )

                connections.add((CONNECTION_NETWORK_MAC, format_mac(cleaned_mac)))

        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device.name if device else "Device",
            manufacturer=device.manufacturer if device else MANUFACTURER,
            model=device.model_name if device else "Cloud Device",
            sw_version=device.firmware_version if device else None,
            hw_version=device.hardware_version if device else None,
            suggested_area=device.room_name if device else None,
            connections=connections,
            configuration_url=get_structure_url(
                device.structure_id if device else None, "devices"
            ),
        )


class GoogleHomeClockNightlightSensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Home Smart Clock Nightlight Status sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "nightlight_status"

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
        enabled_by_default: bool = True,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_nightlight_status"
        self._attr_entity_registry_enabled_default = enabled_by_default

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def native_value(self) -> str:
        """Return nightlight state (on (X%), on, off)."""
        device = self.get_device()
        if not device or not device.online:
            return "unavailable" if not device else "offline"
        state = device.state
        is_on = bool(state.get("nightlight_on", False))
        if not is_on:
            return "off"
        if "brightness" in state:
            bri = state["brightness"]
            return f"on ({bri}%)" if bri is not None else "on"
        return "on"

    @property
    def icon(self) -> str:
        """Return dynamic MDI lightbulb icon."""
        val = str(self.native_value).lower()
        is_active = val.startswith("on")
        return "mdi:lightbulb-on" if is_active else "mdi:lightbulb-outline"

    @property
    def available(self) -> bool:
        """Return availability."""
        device = self.get_device()
        return device is not None and device.online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return nightlight attributes."""
        device = self.get_device()
        if not device:
            return {}
        attrs: dict[str, Any] = {
            "brightness": device.state.get("brightness"),
            "traits": device.traits,
            "state_data": device.state,
        }
        return {
            k: v
            for k, v in attrs.items()
            if v is not None and v != "" and v != [] and v != {}
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info."""
        device = self.get_device()
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device.name if device else "Device",
            manufacturer=device.manufacturer if device else MANUFACTURER,
            model=device.model_name if device else "Cloud Device",
            configuration_url=get_structure_url(
                device.structure_id if device else None, "devices"
            ),
        )


class GoogleHomeBriefsSensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Home Gemini / Home Agent daily activity brief summary sensor."""

    _attr_icon = "mdi:text-box-search-outline"
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        entry_id: str,
        structure_id: str,
        structure_name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.structure_id = structure_id
        self.structure_name = structure_name
        self._attr_unique_id = f"google_home_briefs_{structure_id}"

    @property
    def name(self) -> str:
        """Return name."""
        return f"{self.structure_name} Home Briefs"

    def _extract_briefs_data(self) -> dict[str, Any]:
        """Extract HomeBriefsTrait and Gemini info from raw HomeGraph payload."""
        result: dict[str, Any] = {"status": "available", "briefs": []}
        try:
            auth_client = getattr(self.coordinator.client, "_auth_client", None)
            if auth_client and getattr(auth_client, "homegraph", None):
                raw = auth_client.homegraph.SerializeToString()
                import re

                # Extract strings around HomeBriefsTrait
                matches = re.findall(
                    rb"HomeBriefsTrait[^\xaa]*\x1a[\x01-\x40]([^\x00-\x1f]+)", raw
                )
                brief_texts = [
                    m.decode("utf-8", errors="ignore")
                    for m in matches
                    if len(m) > 3 and b"trait" not in m.lower()
                ]
                if brief_texts:
                    result["briefs"] = brief_texts
        except Exception:
            pass
        return result

    @property
    def native_value(self) -> str:
        """Return brief status."""
        data = self._extract_briefs_data()
        briefs = data.get("briefs", [])
        return str(briefs[0]) if briefs else "No recent summaries"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full briefs metadata."""
        data = self._extract_briefs_data()
        return {
            "structure_id": self.structure_id,
            "structure_name": self.structure_name,
            "all_briefs": data.get("briefs", []),
            "total_briefs": len(data.get("briefs", [])),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return household device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_structure_{self.structure_id}")},
            name=f"Google Home ({self.structure_name})",
            manufacturer=MANUFACTURER,
            model="Google Home Household & Structure",
            configuration_url=get_structure_url(self.structure_id, "devices"),
        )


class GoogleHomeFaceLibrarySensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Nest Aware Familiar Faces Library sensor."""

    _attr_icon = "mdi:account-box-multiple-outline"
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        entry_id: str,
        structure_id: str,
        structure_name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.structure_id = structure_id
        self.structure_name = structure_name
        self._attr_unique_id = f"google_home_face_library_{structure_id}"

    @property
    def name(self) -> str:
        """Return name."""
        return f"{self.structure_name} Familiar Faces"

    def _extract_face_library(self) -> list[str]:
        """Extract FaceLibraryTrait names from raw HomeGraph payload."""
        faces = []
        try:
            auth_client = getattr(self.coordinator.client, "_auth_client", None)
            if auth_client and getattr(auth_client, "homegraph", None):
                raw = auth_client.homegraph.SerializeToString()
                import re

                matches = re.findall(
                    rb"FaceLibraryTrait[^\xaa]*\x1a[\x01-\x30]([^\x00-\x1f]+)", raw
                )
                faces = [
                    m.decode("utf-8", errors="ignore")
                    for m in matches
                    if len(m) > 1 and b"trait" not in m.lower()
                ]
        except Exception:
            pass
        return faces

    @property
    def native_value(self) -> int:
        """Return number of recognized familiar faces."""
        return len(self._extract_face_library())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return recognized familiar face names."""
        faces = self._extract_face_library()
        return {
            "structure_id": self.structure_id,
            "structure_name": self.structure_name,
            "familiar_faces": faces,
            "count": len(faces),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return household device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_structure_{self.structure_id}")},
            name=f"Google Home ({self.structure_name})",
            manufacturer=MANUFACTURER,
            model="Google Home Household & Structure",
            configuration_url=get_structure_url(self.structure_id, "devices"),
        )
