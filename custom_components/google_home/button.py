"""Button platform for Google Home."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN, ICON_REBOOT, ICON_REFRESH
from .coordinator import GoogleHomeDataUpdateCoordinator
from .entity import GoogleHomeBaseEntity
from .models import GoogleHomeDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the Google Home button platform."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator: GoogleHomeDataUpdateCoordinator | None = entry_data.get(
        DATA_COORDINATOR
    )

    if coordinator is None:
        return True

    entities: list[GoogleHomeBaseEntity] = []
    registered_device_ids: set[str] = set()

    def _create_entities_for_device(
        device: GoogleHomeDevice,
    ) -> list[GoogleHomeBaseEntity]:
        registered_device_ids.add(device.device_id)
        return [
            GoogleHomeRebootButton(
                coordinator=coordinator,
                device_id=device.device_id,
                device_name=device.name,
            ),
            GoogleHomeRefreshButton(
                coordinator=coordinator,
                device_id=device.device_id,
                device_name=device.name,
            ),
        ]

    for device in coordinator.data or []:
        entities.extend(_create_entities_for_device(device))

    if entities:
        async_add_entities(entities)

    @callback
    def _async_add_new_devices() -> None:
        """Add entities for devices discovered in subsequent coordinator updates."""
        new_entities: list[GoogleHomeBaseEntity] = []
        for dev in coordinator.data or []:
            if dev.device_id not in registered_device_ids:
                new_entities.extend(_create_entities_for_device(dev))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))
    return True


class GoogleHomeRebootButton(GoogleHomeBaseEntity, ButtonEntity):
    """Button to reboot Google Home speaker."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = ICON_REBOOT
    _attr_entity_registry_enabled_default = False

    @property
    def label(self) -> str:
        """Label to use for unique_id and name."""
        return "reboot"

    async def async_press(self) -> None:
        """Press the button to reboot the device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        await self.client.reboot_device(device=device)


class GoogleHomeRefreshButton(GoogleHomeBaseEntity, ButtonEntity):
    """Button to manually refresh coordinator state."""

    _attr_device_class = ButtonDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = ICON_REFRESH
    _attr_entity_registry_enabled_default = False

    @property
    def label(self) -> str:
        """Label to use for unique_id and name."""
        return "refresh"

    async def async_press(self) -> None:
        """Press the button to refresh data."""
        await self.coordinator.async_request_refresh()
