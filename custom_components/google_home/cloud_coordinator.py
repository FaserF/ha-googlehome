"""DataUpdateCoordinator for Google Home Cloud (HomeGraph)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud_models import CloudHomeDevice
from .const import DOMAIN
from .exceptions import AuthenticationFailed, InvalidMasterToken, TwoFactorRequired

if TYPE_CHECKING:
    from .cloud_api import GoogleHomeCloudClient

_LOGGER: logging.Logger = logging.getLogger(__package__)

STORAGE_VERSION = 1
STORAGE_KEY_NIGHTLIGHT = f"{DOMAIN}_nightlight_states"


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
        self._nightlight_store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_NIGHTLIGHT
        )
        self._nightlight_states: dict[str, dict[str, Any]] = {}
        self._nightlight_loaded: bool = False
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_cloud",
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_load_nightlight_states(self) -> None:
        """Load stored nightlight states from disk."""
        if not self._nightlight_loaded:
            try:
                data = await self._nightlight_store.async_load()
                if isinstance(data, dict):
                    self._nightlight_states = data
            except Exception as err:
                _LOGGER.debug("Could not load stored nightlight states: %s", err)
            self._nightlight_loaded = True

    async def async_set_nightlight_state(
        self, device_id: str, is_on: bool, brightness: int | None = None
    ) -> None:
        """Store and persist last triggered nightlight state for a device."""
        await self._async_load_nightlight_states()
        state_data: dict[str, Any] = {"is_on": is_on}
        if brightness is not None:
            state_data["brightness"] = brightness
        elif (
            device_id in self._nightlight_states
            and "brightness" in self._nightlight_states[device_id]
        ):
            state_data["brightness"] = self._nightlight_states[device_id]["brightness"]
        self._nightlight_states[device_id] = state_data
        try:
            await self._nightlight_store.async_save(self._nightlight_states)
        except Exception as err:
            _LOGGER.warning(
                "Could not persist nightlight state for %s: %s", device_id, err
            )

    def get_nightlight_state(self, device_id: str) -> dict[str, Any] | None:
        """Get the stored last-known nightlight state for a device."""
        return self._nightlight_states.get(device_id)

    async def _async_update_data(self) -> list[CloudHomeDevice]:
        """Update cloud data via HomeGraph client."""
        await self._async_load_nightlight_states()
        try:
            devices = await self.client.async_get_cloud_devices()
            if devices:
                for dev in devices:
                    self._device_cache[dev.device_id] = dev
                    # For smart clock nightlights where Google does not report a separate
                    # nightlight trait in HomeGraph, preserve the last known state set via HA
                    if dev.is_nightlight and dev.device_id in self._nightlight_states:
                        stored = self._nightlight_states[dev.device_id]
                        if "is_on" in stored:
                            dev.state["nightlight_on"] = stored["is_on"]
                        if "brightness" in stored and "brightness" not in dev.state:
                            dev.state["brightness"] = stored["brightness"]
            return devices
        except ConfigEntryAuthFailed:
            raise
        except (AuthenticationFailed, InvalidMasterToken, TwoFactorRequired) as err:
            raise ConfigEntryAuthFailed(
                f"Google Home Cloud authentication expired or invalid: {err}"
            ) from err
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
