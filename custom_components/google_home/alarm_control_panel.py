"""Alarm control panel platform for Google Home & Nest Cloud devices."""

from __future__ import annotations

import logging

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
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
    """Set up Google Home alarm control panel entities."""
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

    def _create_entities() -> list[GoogleHomeCloudAlarmControlPanel]:
        new_ents = []
        for dev in coordinator.data or []:
            if dev.is_security_system and dev.device_id not in registered_ids:
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudAlarmControlPanel(
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


class GoogleHomeCloudAlarmControlPanel(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], AlarmControlPanelEntity
):
    """Google Home Cloud Alarm Control Panel entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize alarm entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_alarm_control_panel"
        self._attr_supported_features = (
            AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.TRIGGER
        )

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return device.name if device else "Google Security System"

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return state."""
        device = self.get_device()
        if not device or not device.online:
            return None
        current_level = device.state.get("currentArmLevel", "DISARMED")
        if current_level in ("ARMED_AWAY", "AWAY"):
            return AlarmControlPanelState.ARMED_AWAY
        if current_level in ("ARMED_HOME", "HOME", "STAY"):
            return AlarmControlPanelState.ARMED_HOME
        if current_level == "TRIGGERED":
            return AlarmControlPanelState.TRIGGERED
        return AlarmControlPanelState.DISARMED

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

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm security system."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.ArmDisarm",
            params={"arm": False},
        )
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Arm home security system."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.ArmDisarm",
            params={"arm": True, "armLevel": "ARMED_HOME"},
        )
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm away security system."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.ArmDisarm",
            params={"arm": True, "armLevel": "ARMED_AWAY"},
        )
        await self.coordinator.async_request_refresh()
