"""Device tracker platform for Google Home Cloud presence."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import (
    SourceType,
    TrackerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
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
        homes: dict[str, str] = {}
        # 1. Query all available homes directly from the client
        if hasattr(coordinator.client, "_get_available_homes_sync"):
            try:
                homes.update(coordinator.client._get_available_homes_sync())
            except Exception:
                pass
        # 2. Add any structures found on individual devices
        for dev in coordinator.data or []:
            if dev.structure_id:
                homes.setdefault(dev.structure_id, dev.structure_name or "Google Home")

        if not homes:
            homes["default_home"] = "Google Home"

        for struct_id, struct_name in homes.items():
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
        """Return the source type."""
        return SourceType.ROUTER

    @property
    def location_name(self) -> str:
        """Return state: home or not_home."""
        # Check if any device or routine in the structure indicates 'Away'
        for dev in self.coordinator.data or []:
            if dev.structure_id == self._structure_id:
                p_state = dev.state.get("presence", dev.state.get("home_away"))
                if p_state:
                    if str(p_state).lower() in (
                        "away",
                        "not_home",
                        "absent",
                        "vacation",
                    ):
                        return STATE_NOT_HOME
        return STATE_HOME

    @property
    def available(self) -> bool:
        """Return True if coordinator is loaded and devices exist."""
        return self.coordinator.last_update_success

    @property
    def device_info(self) -> DeviceInfo:
        """Return unified central main device info for this Google Home household."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_structure_{self._structure_id}")},
            name=f"Google Home ({self._structure_name})",
            manufacturer=MANUFACTURER,
            model="Google Home Household & Structure",
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
