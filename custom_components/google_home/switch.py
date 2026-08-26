"""Switch platform for Google Home."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN, ICON_DO_NOT_DISTURB, ICON_NIGHT_MODE
from .coordinator import GoogleHomeDataUpdateCoordinator
from .entity import GoogleHomeBaseEntity
from .models import GoogleHomeDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the Google Home switch platform."""
    coordinator: GoogleHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]

    entities: list[GoogleHomeBaseEntity] = []
    registered_device_ids: set[str] = set()

    def _create_entities_for_device(
        device: GoogleHomeDevice,
    ) -> list[GoogleHomeBaseEntity]:
        registered_device_ids.add(device.device_id)
        return [
            GoogleHomeDoNotDisturbSwitch(
                coordinator=coordinator,
                device_id=device.device_id,
                device_name=device.name,
            ),
            GoogleHomeNightModeSwitch(
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


class GoogleHomeDoNotDisturbSwitch(GoogleHomeBaseEntity, SwitchEntity):
    """Google Home Do Not Disturb switch entity."""

    _attr_icon = ICON_DO_NOT_DISTURB

    @property
    def label(self) -> str:
        """Label to use for unique_id and name."""
        return "do_not_disturb"

    @property
    def is_on(self) -> bool:
        """Return True if Do Not Disturb is enabled."""
        device = self.get_device()
        return device.get_do_not_disturb() if device else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on Do Not Disturb."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        await self.client.set_do_not_disturb(device=device, enable=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off Do Not Disturb."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        await self.client.set_do_not_disturb(device=device, enable=False)
        self.async_write_ha_state()


class GoogleHomeNightModeSwitch(GoogleHomeBaseEntity, SwitchEntity):
    """Google Home Night Mode switch entity."""

    _attr_icon = ICON_NIGHT_MODE

    @property
    def label(self) -> str:
        """Label to use for unique_id and name."""
        return "night_mode"

    @property
    def is_on(self) -> bool:
        """Return True if Night Mode is enabled."""
        device = self.get_device()
        return device.get_night_mode() if device else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on Night Mode."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        await self.client.set_night_mode_enabled(device=device, enable=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off Night Mode."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        await self.client.set_night_mode_enabled(device=device, enable=False)
        self.async_write_ha_state()
