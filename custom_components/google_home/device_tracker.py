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
from .const import DATA_CLOUD_COORDINATOR, DOMAIN, MANUFACTURER, get_structure_url

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
    """Representation of Google Home Home & Away Presence Tracker.

    Note: The Google Foyer API does not expose reliable presence/home-away state
    data. This tracker is provided as a placeholder but will report 'home' unless
    the device state payload contains a 'presence' or 'home_away' key.
    Disabled by default to avoid confusion.
    """

    _attr_icon = "mdi:home-account"
    _attr_entity_registry_enabled_default = True

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
        return f"{self._structure_name} Presence"

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.ROUTER

    def _get_structure_presence_and_attendance(self) -> tuple[str, str | None]:
        """Extract AreaPresenceStateTrait and AreaAttendanceStateTrait from cached HomeGraph."""
        presence = "PRESENCE_STATE_OCCUPIED"
        attendance = None
        try:
            auth_client = getattr(self.coordinator.client, "_auth_client", None)
            if not auth_client or not getattr(auth_client, "homegraph", None):
                return presence, attendance
            raw = auth_client.homegraph.SerializeToString()
            import re

            # Search AreaPresenceStateTrait in protobuf payload
            m_pres = re.search(
                rb"AreaPresenceStateTrait[^\x00-\x1f]*presenceState[^\x00-\x1f]{0,50}(PRESENCE_STATE_[A-Z]+)",
                raw,
            )
            if m_pres:
                presence = m_pres.group(1).decode("utf-8", errors="ignore")

            # Search AreaAttendanceStateTrait in protobuf payload
            m_att = re.search(
                rb"AreaAttendanceStateTrait[^\x00-\x1f]*attendanceState[^\x00-\x1f]{0,50}(ATTENDANCE_STATE_[A-Z_]+)",
                raw,
            )
            if m_att:
                raw_att = m_att.group(1).decode("utf-8", errors="ignore")
                # Format into friendly text: e.g. "ALL_HOUSEHOLD_MEMBERS" -> "all_household_members"
                attendance = raw_att.replace("ATTENDANCE_STATE_", "").lower()
        except Exception:
            pass
        return presence, attendance

    @property
    def state(self) -> str:
        """Return state: home or not_home based on live Google HomeGraph presence state."""
        pres, _ = self._get_structure_presence_and_attendance()
        if "VACANT" in pres or "UNOCCUPIED" in pres or "AWAY" in pres:
            return STATE_NOT_HOME

        # Also check if any device state specifically signals AWAY
        for dev in self.coordinator.data or []:
            if dev.structure_id == self._structure_id:
                p_state = dev.state.get("presence", dev.state.get("home_away"))
                if p_state and str(p_state).lower() in (
                    "away",
                    "not_home",
                    "absent",
                    "vacation",
                    "vacant",
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
            configuration_url=get_structure_url(self._structure_id, "devices"),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return structure presence attributes."""
        pres_raw, attendance = self._get_structure_presence_and_attendance()
        devices_in_structure = [
            dev.name
            for dev in self.coordinator.data or []
            if dev.structure_id == self._structure_id
        ]
        attrs: dict[str, Any] = {
            "structure_id": self._structure_id,
            "structure_name": self._structure_name,
            "presence_raw": pres_raw,
            "total_devices": len(devices_in_structure),
            "devices": devices_in_structure,
        }
        if attendance:
            attrs["attendance_state"] = attendance
            attrs["all_members_present"] = "all_household_members" in attendance
        return attrs
