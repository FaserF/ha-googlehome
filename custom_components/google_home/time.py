"""Time platform for Google Home Assistant SDK alarm/timer scheduling."""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .assistant_helper import format_command
from .const import (
    CONF_OPERATION_MODE,
    CONF_THIRD_PARTY_ENTITY_MODE,
    DATA_COORDINATOR,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    ICON_ALARMS,
    MODE_HYBRID,
    THIRD_PARTY_MODE_ASSISTANT_SDK,
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
    """Set up the Google Home time platform."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator: GoogleHomeDataUpdateCoordinator | None = entry_data.get(
        DATA_COORDINATOR
    )

    if coordinator is None:
        return True

    mode = entry.options.get(
        CONF_OPERATION_MODE,
        entry.data.get(CONF_OPERATION_MODE, MODE_HYBRID),
    )
    third_party_mode = entry.options.get(
        CONF_THIRD_PARTY_ENTITY_MODE,
        entry.data.get(CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE),
    )

    # Only add time entities if mode is HYBRID and third_party_mode is ASSISTANT_SDK
    if mode != MODE_HYBRID or third_party_mode != THIRD_PARTY_MODE_ASSISTANT_SDK:
        return True

    entities: list[GoogleHomeBaseEntity] = []
    registered_device_ids: set[str] = set()

    def _create_entities_for_device(
        device: GoogleHomeDevice,
    ) -> list[GoogleHomeBaseEntity]:
        # Only add for local speaker devices that support alarms / have auth_token
        if not device.auth_token:
            return []
        registered_device_ids.add(device.device_id)
        return [
            GoogleHomeSetAlarmTime(
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


class GoogleHomeSetAlarmTime(GoogleHomeBaseEntity, TimeEntity):
    """Time entity to set an alarm on a specific Google Home device via Assistant SDK."""

    _attr_icon = ICON_ALARMS
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: GoogleHomeDataUpdateCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the time entity."""
        super().__init__(coordinator, device_id, device_name)
        self._attr_native_value: time | None = None

    @property
    def label(self) -> str:
        """Label to use for unique_id and name."""
        return "set_alarm"

    def _find_target_media_player(self) -> str | None:
        """Find matching media_player entity for this device in Home Assistant."""
        dev_name = self.device_name.strip().lower()
        dev_slug = dev_name.replace(" ", "_")

        for state in self.hass.states.async_all("media_player"):
            if dev_slug in state.entity_id:
                return state.entity_id
            fname = state.attributes.get("friendly_name", "").strip().lower()
            if fname == dev_name:
                return state.entity_id

        return None

    async def _async_send_assistant_command(self, command: str) -> None:
        """Forward command via Google Assistant SDK targeted to this specific device."""
        if self.hass.services.has_service("google_assistant_sdk", "send_text_command"):
            try:
                service_data: dict[str, Any] = {"command": command}
                target_mp = self._find_target_media_player()
                if target_mp:
                    service_data["media_player"] = target_mp

                _LOGGER.debug(
                    "Sending Assistant SDK command for %s: %s (data=%s)",
                    self.device_name,
                    command,
                    service_data,
                )
                await self.hass.services.async_call(
                    "google_assistant_sdk",
                    "send_text_command",
                    service_data,
                    blocking=False,
                )
            except Exception as ex:
                _LOGGER.warning(
                    "Error invoking google_assistant_sdk for %s: %s",
                    self.device_name,
                    ex,
                )

    async def async_set_value(self, value: time) -> None:
        """Set a new alarm time on this specific Google Home speaker."""
        self._attr_native_value = value
        self.async_write_ha_state()

        time_str = value.strftime("%H:%M")
        target_mp = self._find_target_media_player()
        action = "set_alarm" if target_mp else "set_alarm_named"
        cmd = format_command(
            self.hass,
            action,
            self.device_name,
            time=time_str,
        )
        await self._async_send_assistant_command(cmd)
