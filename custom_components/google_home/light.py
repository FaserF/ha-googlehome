"""Light platform for Google Home Cloud devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .cloud_models import CloudHomeDevice
from .const import (
    CONF_THIRD_PARTY_ENTITY_MODE,
    DATA_CLOUD_COORDINATOR,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    MANUFACTURER,
    THIRD_PARTY_MODE_READONLY,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Google Home light entities."""
    if (
        DOMAIN not in hass.data
        or entry.entry_id not in hass.data[DOMAIN]
        or DATA_CLOUD_COORDINATOR not in hass.data[DOMAIN][entry.entry_id]
    ):
        return True

    coordinator: GoogleHomeCloudDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_CLOUD_COORDINATOR]

    third_party_mode = entry.options.get(
        CONF_THIRD_PARTY_ENTITY_MODE,
        entry.data.get(CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE),
    )

    registered_ids: set[str] = set()

    def _create_entities() -> list[GoogleHomeCloudLight]:
        new_ents = []
        for dev in coordinator.data or []:
            if (
                dev.is_light
                and dev.device_id not in registered_ids
                and (
                    not dev.is_third_party
                    or third_party_mode != THIRD_PARTY_MODE_READONLY
                )
            ):
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudLight(
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


class GoogleHomeCloudLight(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], LightEntity
):
    """Google Home Cloud Light entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_light"
        self._attr_supported_color_modes = {ColorMode.ONOFF}
        self._attr_color_mode = ColorMode.ONOFF

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        if not device:
            return "Google Light"
        # For Smart Clocks (Lenovo Smart Clock / Uhren), append 'Nachtlicht' for clarity
        if any(
            k in (device.hardware_model or "").lower() or k in device.name.lower()
            for k in ("clock", "uhr", "cd-")
        ):
            return f"{device.name} Nachtlicht"
        return device.name

    @property
    def is_on(self) -> bool:
        """Return on status."""
        device = self.get_device()
        if not device:
            return False
        return bool(device.state.get("on", False))

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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        device = self.get_device()
        if device and "action.devices.traits.NightLight" in (device.traits or []):
            await self.coordinator.client.async_execute_command(
                device_id=self.device_id,
                command="action.devices.commands.SetNightLight",
                params={"on": True},
            )
        else:
            await self.coordinator.client.async_execute_command(
                device_id=self.device_id,
                command="action.devices.commands.OnOff",
                params={"on": True},
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        device = self.get_device()
        if device and "action.devices.traits.NightLight" in (device.traits or []):
            await self.coordinator.client.async_execute_command(
                device_id=self.device_id,
                command="action.devices.commands.SetNightLight",
                params={"on": False},
            )
        else:
            await self.coordinator.client.async_execute_command(
                device_id=self.device_id,
                command="action.devices.commands.OnOff",
                params={"on": False},
            )
        await self.coordinator.async_request_refresh()
