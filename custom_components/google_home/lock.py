"""Lock platform for Google Home Cloud devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .assistant_helper import format_command
from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .cloud_models import CloudHomeDevice
from .const import (
    CONF_THIRD_PARTY_ENTITY_MODE,
    DATA_CLOUD_COORDINATOR,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    MANUFACTURER,
    THIRD_PARTY_MODE_ASSISTANT_SDK,
    THIRD_PARTY_MODE_DIRECT_CLOUD,
    THIRD_PARTY_MODE_READONLY,
    get_structure_url,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Google Home lock entities."""
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

    def _create_entities() -> list[GoogleHomeCloudLock]:
        new_ents = []
        for dev in coordinator.data or []:
            if (
                dev.is_lock
                and dev.device_id not in registered_ids
                and (
                    not dev.is_third_party
                    or third_party_mode != THIRD_PARTY_MODE_READONLY
                )
            ):
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudLock(
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


class GoogleHomeCloudLock(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], LockEntity
):
    """Google Home Cloud Lock entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize lock entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_lock"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return device.name if device else "Google Lock"

    @property
    def is_locked(self) -> bool:
        """Return True if locked."""
        device = self.get_device()
        if not device:
            return True
        return bool(device.state.get("isLocked", True))

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
            configuration_url=get_structure_url(
                device.structure_id if device else None, "devices"
            ),
        )

    async def _async_send_assistant_command(self, command: str) -> None:
        """Forward command via Google Assistant SDK if installed and available."""
        if self.hass.services.has_service("google_assistant_sdk", "send_text_command"):
            try:
                _LOGGER.debug("Sending Assistant SDK lock command: %s", command)
                await self.hass.services.async_call(
                    "google_assistant_sdk",
                    "send_text_command",
                    {"command": command},
                    blocking=False,
                )
            except Exception as ex:
                _LOGGER.warning("Error invoking google_assistant_sdk: %s", ex)

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        device = self.get_device()
        if device:
            device.state["isLocked"] = True

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK and device:
            await self._async_send_assistant_command(
                format_command(self.hass, "lock", device.name)
            )
        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD and device:
            await self.coordinator.client.async_execute_command(
                device_id=self.device_id,
                command="action.devices.commands.LockUnlock",
                params={"lock": True},
            )
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        device = self.get_device()
        if device:
            device.state["isLocked"] = False

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK and device:
            await self._async_send_assistant_command(
                format_command(self.hass, "unlock", device.name)
            )

        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD and device:
            await self.coordinator.client.async_execute_command(
                device_id=self.device_id,
                command="action.devices.commands.LockUnlock",
                params={"lock": False},
            )
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()
