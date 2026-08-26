"""Binary sensor platform for Google Home & Nest Cloud devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .cloud_models import CloudHomeDevice
from .const import DATA_CLOUD_COORDINATOR, DOMAIN, MANUFACTURER

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Google Home binary sensor entities."""
    if (
        DOMAIN not in hass.data
        or entry.entry_id not in hass.data[DOMAIN]
        or DATA_CLOUD_COORDINATOR not in hass.data[DOMAIN][entry.entry_id]
    ):
        return True

    coordinator: GoogleHomeCloudDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_CLOUD_COORDINATOR]

    registered_ids: set[str] = set()
    registered_sound_ids: set[str] = set()

    def _create_entities() -> list[BinarySensorEntity]:
        new_ents: list[BinarySensorEntity] = []
        for dev in coordinator.data or []:
            if dev.is_binary_sensor and dev.device_id not in registered_ids:
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudBinarySensor(
                        coordinator=coordinator, device_id=dev.device_id
                    )
                )
            # Create sound sensing sensor for Google speakers and displays
            if (
                (
                    "SPEAKER" in dev.device_type
                    or "DISPLAY" in dev.device_type
                    or not dev.is_third_party
                )
                and not dev.is_automation_routine
                and dev.device_id not in registered_sound_ids
            ):
                registered_sound_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeSoundSensingBinarySensor(
                        coordinator=coordinator, device_id=dev.device_id
                    )
                )
        return new_ents

    entities = _create_entities()

    if entities:
        async_add_entities(entities)

    @callback
    def _async_add_new_devices() -> None:
        new_ents = _create_entities()
        if new_ents:
            async_add_entities(new_ents)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))
    return True


class GoogleHomeCloudBinarySensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], BinarySensorEntity
):
    """Google Home Cloud Binary Sensor entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_binary_sensor"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return device.name if device else "Google Sensor"

    @property
    def is_on(self) -> bool:
        """Return sensor state."""
        device = self.get_device()
        if not device:
            return False
        # Contact sensor, motion, occupancy, doorbell press, or Nest Aware AI detections
        return bool(
            device.state.get("openPercent", 0) > 0
            or device.state.get("occupancy", "UNOCCUPIED") == "OCCUPIED"
            or device.state.get("motionDetected", False)
            or device.state.get("doorbellPressed", False)
            or device.state.get("personDetected", False)
            or device.state.get("packageDelivered", False)
            or device.state.get("packageRetrieved", False)
            or device.state.get("animalDetected", False)
            or device.state.get("vehicleDetected", False)
            or device.state.get("soundDetected", False)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return Nest Aware AI & event attributes."""
        device = self.get_device()
        if not device:
            return {}
        return {
            "person_detected": bool(device.state.get("personDetected", False)),
            "package_delivered": bool(device.state.get("packageDelivered", False)),
            "package_retrieved": bool(device.state.get("packageRetrieved", False)),
            "animal_detected": bool(device.state.get("animalDetected", False)),
            "vehicle_detected": bool(device.state.get("vehicleDetected", False)),
            "sound_detected": bool(device.state.get("soundDetected", False)),
            "familiar_faces": device.state.get("familiarFaces", []),
            "event_timestamp": device.state.get("eventTimestamp"),
            "event_zone": device.state.get("activityZone"),
        }

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return device class."""
        device = self.get_device()
        if not device:
            return None
        if "DOORBELL" in device.device_type:
            return BinarySensorDeviceClass.DOOR
        if "action.devices.traits.OccupancySensing" in device.traits:
            return BinarySensorDeviceClass.OCCUPANCY
        if device.state.get("personDetected"):
            return BinarySensorDeviceClass.PRESENCE
        if device.state.get("soundDetected"):
            return BinarySensorDeviceClass.SOUND
        return BinarySensorDeviceClass.MOTION

    @property
    def available(self) -> bool:
        """Return available status."""
        device = self.get_device()
        return device.online if device else False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info."""
        device = self.get_device()
        connections = set()
        if device and device.mac_address:
            from homeassistant.helpers.device_registry import (
                CONNECTION_NETWORK_MAC,
                format_mac,
            )

            connections.add((CONNECTION_NETWORK_MAC, format_mac(device.mac_address)))

        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.name,
            manufacturer=device.manufacturer if device else MANUFACTURER,
            model=device.model_name if device else "Google Cloud Device",
            sw_version=device.firmware_version if device else None,
            hw_version=device.hardware_version if device else None,
            connections=connections,
            configuration_url="https://home.google.com/",
        )


class GoogleHomeSoundSensingBinarySensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], BinarySensorEntity
):
    """Google Home Nest Aware Sound & Smoke/CO Alarm Sensing binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.SMOKE
    _attr_icon = "mdi:smoke-detector-alert"
    # Disabled by default
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_sound_sensing"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return (
            f"{device.name} Smoke/CO Alarm Sound" if device else "Smoke/CO Alarm Sound"
        )

    @property
    def is_on(self) -> bool:
        """Return True if smoke or critical sound is detected."""
        device = self.get_device()
        if not device:
            return False
        return bool(
            device.state.get("smokeDetected", False)
            or device.state.get("coDetected", False)
            or device.state.get("alarmSoundDetected", False)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sound sensing details."""
        device = self.get_device()
        if not device:
            return {}
        return {
            "smoke_detected": bool(device.state.get("smokeDetected", False)),
            "co_detected": bool(device.state.get("coDetected", False)),
            "glass_break_detected": bool(device.state.get("glassBreakDetected", False)),
            "sound_detected": bool(device.state.get("soundDetected", False)),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info."""
        device = self.get_device()
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device.name if device else "Google Device",
            manufacturer=device.manufacturer if device else MANUFACTURER,
            model=device.model_name if device else "Google Device",
            configuration_url="https://home.google.com/",
        )
