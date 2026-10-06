"""Update platform for Google Home."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_COORDINATOR,
    DOCS_FIRMWARE_RELEASE_NOTES_URL,
    DOMAIN,
)
from .coordinator import GoogleHomeDataUpdateCoordinator
from .entity import GoogleHomeBaseEntity
from .models import GoogleHomeDevice

if TYPE_CHECKING:
    from .coordinator import GoogleHomeDataUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the Google Home update platform."""
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
            GoogleHomeUpdateEntity(
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


class GoogleHomeUpdateEntity(GoogleHomeBaseEntity, UpdateEntity):
    """Update entity representing Google Home / Nest firmware status."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    @property
    def label(self) -> str:
        """Label to use for unique_id and translation."""
        return "firmware_update"

    @property
    def installed_version(self) -> str | None:
        """Version installed and currently in use."""
        device = self.get_device()
        return device.firmware_version if device else None

    @property
    def latest_version(self) -> str | None:
        """Latest version available for install."""
        device = self.get_device()
        if not device:
            return None
        return device.latest_firmware_version or device.firmware_version

    @property
    def release_url(self) -> str | None:
        """URL for release notes."""
        return DOCS_FIRMWARE_RELEASE_NOTES_URL

    @property
    def release_summary(self) -> str | None:
        """Summary of the release."""
        device = self.get_device()
        return device.release_summary if device else None

    @property
    def in_progress(self) -> bool:
        """Update installation progress boolean."""
        device = self.get_device()
        if not device or not device.ota_status:
            return False

        status = str(device.ota_status).lower()
        return bool("download" in status or "progress" in status or "install" in status)

    @property
    def update_percentage(self) -> int | None:
        """Update installation progress percentage."""
        device = self.get_device()
        if not device or not device.ota_status:
            return None

        status = str(device.ota_status).lower()
        if "download" in status or "progress" in status or "install" in status:
            import re

            match = re.search(r"(\d+)%?", status)
            if match:
                try:
                    pct = int(match.group(1))
                    if 0 <= pct <= 100:
                        return pct
                except ValueError:
                    pass
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device-specific firmware state attributes."""
        device = self.get_device()
        attrs: dict[str, Any] = {}
        if device:
            if device.hardware:
                attrs["hardware"] = device.hardware
            if device.ota_status:
                attrs["ota_status"] = device.ota_status
            if device.cast_uuid:
                attrs["cast_uuid"] = device.cast_uuid
            if device.ip_address:
                attrs["ip_address"] = device.ip_address
        return attrs

    async def async_install(
        self, version: str | None = None, backup: bool = False, **kwargs: Any
    ) -> None:
        """Trigger update installation on the Google Home device via reboot."""
        device = self.get_device()
        if device is None:
            _LOGGER.error(
                "Device %s not found to initiate firmware update.", self.device_name
            )
            return

        _LOGGER.info(
            "Rebooting %s (%s) to initiate Google Home firmware update",
            self.device_name,
            device.ip_address,
        )
        res = await self.client.reboot_device(device=device)
        _LOGGER.debug("Reboot response from %s: %s", self.device_name, res)
        await self.coordinator.async_request_refresh()
