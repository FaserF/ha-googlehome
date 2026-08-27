"""DataUpdateCoordinator for Google Home Cloud (HomeGraph)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud_models import CloudHomeDevice
from .const import DOMAIN

if TYPE_CHECKING:
    from .cloud_api import GoogleHomeCloudClient

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeCloudDataUpdateCoordinator(
    DataUpdateCoordinator[list[CloudHomeDevice]]
):
    """Class to manage fetching Google Home Cloud (HomeGraph) data."""

    client: GoogleHomeCloudClient
    cloud_client: GoogleHomeCloudClient

    def __init__(
        self,
        hass: HomeAssistant,
        client: GoogleHomeCloudClient,
        update_interval: int,
    ) -> None:
        """Initialize cloud coordinator."""
        self.client = client
        self.cloud_client = client
        self._device_cache: dict[str, CloudHomeDevice] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_cloud",
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> list[CloudHomeDevice]:
        """Update cloud data via HomeGraph client."""
        try:
            devices = await self.client.async_get_cloud_devices()
            if devices:
                for dev in devices:
                    self._device_cache[dev.device_id] = dev
            return devices
        except Exception as err:
            raise UpdateFailed(
                f"Error updating Google Home Cloud HomeGraph: {err}"
            ) from err

    def get_device(self, device_id: str) -> CloudHomeDevice | None:
        """Get device by ID from latest coordinator data."""
        if self.data:
            for device in self.data:
                if device.device_id == device_id:
                    return device
        return self._device_cache.get(device_id)
