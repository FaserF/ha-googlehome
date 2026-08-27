"""Base entity for Google Home."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import GoogleHomeDataUpdateCoordinator
from .models import GoogleHomeDevice

if TYPE_CHECKING:
    from .api import GlocaltokensApiClient

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeBaseEntity(CoordinatorEntity[GoogleHomeDataUpdateCoordinator]):
    """Base entity for all Google Home entities."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: GoogleHomeDataUpdateCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize base entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        self.device_name = device_name
        self._attr_unique_id = f"{device_id}_{self.label}"
        self._attr_translation_key = self.label

    @property
    def label(self) -> str:
        """Label to use for unique_id and name."""
        raise NotImplementedError

    @property
    def client(self) -> GlocaltokensApiClient:
        """Return the API client."""
        return self.coordinator.client

    def get_device(self) -> GoogleHomeDevice | None:
        """Return device from coordinator data."""
        return self.coordinator.get_device(self.device_id)

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        device = self.get_device()
        return device is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device = self.get_device()
        model = device.hardware if device and device.hardware else "Google Home / Nest"
        firmware = device.firmware_version if device else None
        connections = set()
        if device and (device.mac_address or device.get_bluetooth_mac()):
            from homeassistant.helpers.device_registry import (
                CONNECTION_NETWORK_MAC,
                format_mac,
            )

            mac = device.mac_address or device.get_bluetooth_mac()
            if mac:
                connections.add((CONNECTION_NETWORK_MAC, format_mac(mac)))

        manufacturer = device.manufacturer if device else MANUFACTURER
        model = device.model_name if device else "Google Home / Nest"

        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.device_name,
            manufacturer=manufacturer,
            model=model,
            sw_version=firmware,
            connections=connections,
            configuration_url="https://home.google.com/",
        )
