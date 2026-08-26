"""Cover platform for Google Home Cloud devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
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
    """Set up Google Home cover entities."""
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

    def _create_entities() -> list[GoogleHomeCloudCover]:
        new_ents = []
        for dev in coordinator.data or []:
            if dev.is_cover and dev.device_id not in registered_ids:
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudCover(
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


class GoogleHomeCloudCover(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], CoverEntity
):
    """Google Home Cloud Cover entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize cover entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_cover"
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
        )

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return device.name if device else "Google Cover"

    @property
    def is_closed(self) -> bool | None:
        """Return True if closed."""
        device = self.get_device()
        if not device:
            return None
        percent = device.state.get("openPercent", 0)
        return percent == 0

    @property
    def current_cover_position(self) -> int | None:
        """Return position (0-100)."""
        device = self.get_device()
        if not device:
            return None
        return int(device.state.get("openPercent", 100))

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

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open cover."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.OpenClose",
            params={"openPercent": 100},
        )
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.OpenClose",
            params={"openPercent": 0},
        )
        await self.coordinator.async_request_refresh()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        pos = kwargs.get("position", 100)
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.OpenClose",
            params={"openPercent": pos},
        )
        await self.coordinator.async_request_refresh()
