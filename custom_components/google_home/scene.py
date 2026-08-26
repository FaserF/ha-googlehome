"""Scene platform for Google Home Automations and Routines."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene
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
    """Set up Google Home scene entities."""
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

    def _create_entities() -> list[GoogleHomeCloudScene]:
        new_ents = []
        for dev in coordinator.data or []:
            if dev.is_automation_routine and dev.device_id not in registered_ids:
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudScene(
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


class GoogleHomeCloudScene(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], Scene
):
    """Google Home Cloud Scene / Routine entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize scene entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_scene"
        self._attr_icon = "mdi:play-circle-outline"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return device.name if device else "Google Automation"

    @property
    def available(self) -> bool:
        """Return available status."""
        device = self.get_device()
        return device.online if device else False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info."""
        device = self.get_device()
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.name,
            manufacturer=device.manufacturer if device else MANUFACTURER,
            model="Google Home Automation / Routine",
        )

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the Google Home automation or routine."""
        _LOGGER.info("Triggering Google Home Automation: %s", self.name)
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.ActivateScene",
            params={"deactivate": False},
        )
        await self.coordinator.async_request_refresh()
