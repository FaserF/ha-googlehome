"""Switch platform for Google Home."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .cloud_models import CloudHomeDevice
from .const import (
    DATA_COORDINATOR,
    DOMAIN,
    ICON_DO_NOT_DISTURB,
    ICON_NIGHT_MODE,
    MANUFACTURER,
)
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
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator: GoogleHomeDataUpdateCoordinator | None = entry_data.get(
        DATA_COORDINATOR
    )
    cloud_coordinator = entry_data.get("cloud_coordinator")

    entities: list[Any] = []
    registered_device_ids: set[str] = set()

    if coordinator is not None:

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

    if cloud_coordinator is not None:
        registered_cloud_ids: set[str] = set()

        def _create_cloud_entities() -> list[GoogleHomeCloudSwitch]:
            new_ents = []
            for cdev in cloud_coordinator.data or []:
                if cdev.is_switch and cdev.device_id not in registered_cloud_ids:
                    registered_cloud_ids.add(cdev.device_id)
                    new_ents.append(
                        GoogleHomeCloudSwitch(
                            coordinator=cloud_coordinator,
                            device_id=cdev.device_id,
                        )
                    )
            return new_ents

        cloud_ents = _create_cloud_entities()
        if cloud_ents:
            entities.extend(cloud_ents)

        @callback
        def _async_add_new_cloud_switches() -> None:
            new_ents = _create_cloud_entities()
            if new_ents:
                async_add_entities(new_ents)

        entry.async_on_unload(
            cloud_coordinator.async_add_listener(_async_add_new_cloud_switches)
        )

    if entities:
        async_add_entities(entities)

    return True


class GoogleHomeCloudSwitch(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SwitchEntity
):
    """Google Home Cloud Switch entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_switch"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return device.name if device else "Google Switch"

    @property
    def device_class(self) -> SwitchDeviceClass | None:
        """Return device class based on type."""
        device = self.get_device()
        if not device:
            return SwitchDeviceClass.SWITCH
        dtype = device.device_type.upper()
        if "OUTLET" in dtype or "PLUG" in dtype:
            return SwitchDeviceClass.OUTLET
        return SwitchDeviceClass.SWITCH

    @property
    def icon(self) -> str | None:
        """Return specialized icon for appliances like fryers, coffee makers, etc."""
        device = self.get_device()
        if not device:
            return None
        dtype = device.device_type.upper()
        if "FRYER" in dtype:
            return "mdi:pot-steam" if self.is_on else "mdi:pot"
        if "COFFEE_MAKER" in dtype:
            return "mdi:coffee-maker"
        if "KETTLE" in dtype:
            return "mdi:kettle"
        if "TOASTER" in dtype:
            return "mdi:toaster"
        if "OUTLET" in dtype or "PLUG" in dtype:
            return "mdi:power-socket-eu" if self.is_on else "mdi:power-socket-eu"
        return None

    @property
    def is_on(self) -> bool:
        """Return True if on."""
        device = self.get_device()
        return bool(device.state.get("on", False)) if device else False

    @property
    def available(self) -> bool:
        """Return True if available."""
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on switch."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.OnOff",
            params={"on": True},
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off switch."""
        await self.coordinator.client.async_execute_command(
            device_id=self.device_id,
            command="action.devices.commands.OnOff",
            params={"on": False},
        )
        await self.coordinator.async_request_refresh()


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
    _attr_entity_registry_enabled_default = False

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
