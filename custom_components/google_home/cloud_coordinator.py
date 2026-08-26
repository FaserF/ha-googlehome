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

    def __init__(
        self,
        hass: HomeAssistant,
        client: GoogleHomeCloudClient,
        update_interval: int,
    ) -> None:
        """Initialize cloud coordinator."""
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_cloud",
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> list[CloudHomeDevice]:
        """Update cloud data via HomeGraph client."""
        try:
            return await self.client.async_get_cloud_devices()
        except Exception as err:
            raise UpdateFailed(
                f"Error updating Google Home Cloud HomeGraph: {err}"
            ) from err

    def get_device(self, device_id: str) -> CloudHomeDevice | None:
        """Get device by ID from latest coordinator data."""
        if not self.data:
            return None
        for device in self.data:
            if device.device_id == device_id:
                return device
        return None
