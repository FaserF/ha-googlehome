"""Lock platform for Google Home Cloud devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    """Set up Google Home lock entities."""
    if (
        DOMAIN not in hass.data
        or entry.entry_id not in hass.data[DOMAIN]
        or DATA_CLOUD_COORDINATOR not in hass.data[DOMAIN][entry.entry_id]
    ):
        return True

    coordinator: GoogleHomeCloudDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_CLOUD_COORDINATOR]

    entities: list[GoogleHomeCloudLock] = []
    for device in coordinator.data or []:
        if device.is_lock:
            entities.append(
                GoogleHomeCloudLock(
                    coordinator=coordinator,
                    device_id=device.device_id,
                )
            )

    async_add_entities(entities)
    return True


class GoogleHomeCloudLock(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], LockEntity
):
    """Google Home Cloud Lock entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize lock entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_lock"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return device.name if device else "Google Lock"

    @property
    def is_locked(self) -> bool:
        """Return True if locked."""
        device = self.get_device()
        if not device:
            return True
        return bool(device.state.get("isLocked", True))

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
            from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

            connections.add((CONNECTION_NETWORK_MAC, device.mac_address))

        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.name,
            manufacturer=device.agent_name
            if device and device.agent_name
            else MANUFACTURER,
            model=device.hardware_model
            if device and device.hardware_model
            else "Google Smart Lock",
            sw_version=device.firmware_version if device else None,
            hw_version=device.hardware_version if device else None,
            connections=connections,
            configuration_url="https://home.google.com/",
        )

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.LockUnlock",
            params={"lock": True},
        )
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.LockUnlock",
            params={"lock": False},
        )
        await self.coordinator.async_request_refresh()
