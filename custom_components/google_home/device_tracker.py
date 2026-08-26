"""Device tracker platform for Google Home Cloud presence."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .const import DATA_CLOUD_COORDINATOR, DOMAIN, MANUFACTURER

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Google Home structure presence tracker entities."""
    if (
        DOMAIN not in hass.data
        or entry.entry_id not in hass.data[DOMAIN]
        or DATA_CLOUD_COORDINATOR not in hass.data[DOMAIN][entry.entry_id]
    ):
        return True

    coordinator: GoogleHomeCloudDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_CLOUD_COORDINATOR]

    registered_structures: set[str] = set()

    def _create_trackers() -> list[GoogleHomePresenceTracker]:
        new_trackers = []
        # Find all distinct Google Home structures in the cloud coordinator data
        for dev in coordinator.data or []:
            struct_id = dev.structure_id or "default_home"
            struct_name = dev.structure_name or "Google Home"
            if struct_id not in registered_structures:
                registered_structures.add(struct_id)
                new_trackers.append(
                    GoogleHomePresenceTracker(
                        coordinator=coordinator,
                        entry_id=entry.entry_id,
                        structure_id=struct_id,
                        structure_name=struct_name,
                    )
                )
        return new_trackers

    trackers = _create_trackers()
    if trackers:
        async_add_entities(trackers)

    @callback
    def _async_add_new_trackers() -> None:
        new_tr = _create_trackers()
        if new_tr:
            async_add_entities(new_tr)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_trackers))
    return True


class GoogleHomePresenceTracker(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], TrackerEntity
):
    """Representation of Google Home Home & Away Presence Tracker."""

    _attr_icon = "mdi:home-account"

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        entry_id: str,
        structure_id: str,
        structure_name: str,
    ) -> None:
        """Initialize Google Home presence tracker."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._structure_id = structure_id
        self._structure_name = structure_name
        self._attr_unique_id = f"google_home_presence_{structure_id}"

    @property
    def name(self) -> str:
        """Return the presence tracker friendly name."""
        return f"{self._structure_name} Anwesenheit"

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device tracker."""
        return SourceType.ROUTER

    @property
    def location_name(self) -> str:
        """Return location name (home or not_home)."""
        # Determine if any device or routine in the structure indicates 'Home' or 'Away'
        # Default to 'home' when connected and devices online
        for dev in self.coordinator.data or []:
            if dev.structure_id == self._structure_id:
                # Check for explicit home/away presence state if available
                p_state = dev.state.get("presence", dev.state.get("home_away"))
                if p_state:
                    if str(p_state).lower() in (
                        "away",
                        "not_home",
                        "absent",
                        "vacation",
                    ):
                        return "not_home"
                    return "home"
        return "home"

    @property
    def device_info(self) -> DeviceInfo:
        """Return unified central main device info for the entire Google Home household."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_hub")},
            name=f"Google Home ({self._structure_name})",
            manufacturer=MANUFACTURER,
            model="Google Home Hub & Household",
            sw_version="Cloud HomeGraph",
            configuration_url="https://home.google.com/",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return structure presence attributes."""
        devices_in_structure = [
            dev.name
            for dev in self.coordinator.data or []
            if dev.structure_id == self._structure_id
        ]
        return {
            "structure_id": self._structure_id,
            "structure_name": self._structure_name,
            "total_devices": len(devices_in_structure),
            "devices": devices_in_structure,
        }
