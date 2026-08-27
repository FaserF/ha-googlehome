"""Number platform for Google Home."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .assistant_helper import format_command
from .const import (
    CONF_THIRD_PARTY_ENTITY_MODE,
    DATA_COORDINATOR,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    ICON_ALARM_VOLUME_HIGH,
    ICON_ALARM_VOLUME_LOW,
    ICON_ALARM_VOLUME_MID,
    ICON_ALARM_VOLUME_OFF,
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
    """Set up the Google Home number platform."""
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
            GoogleHomeAlarmVolumeNumber(
                coordinator=coordinator,
                device_id=device.device_id,
                device_name=device.name,
            ),
            GoogleHomeDeviceVolumeNumber(
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


class GoogleHomeAlarmVolumeNumber(GoogleHomeBaseEntity, NumberEntity):
    """Google Home Alarm Volume slider entity."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "%"

    @property
    def label(self) -> str:
        """Label to use for unique_id and name."""
        return "alarm_volume"

    @property
    def icon(self) -> str:
        """Dynamically return volume icon based on current volume level."""
        val = self.native_value
        if val is None or val == 0:
            return ICON_ALARM_VOLUME_OFF
        if val < 33:
            return ICON_ALARM_VOLUME_LOW
        if val < 66:
            return ICON_ALARM_VOLUME_MID
        return ICON_ALARM_VOLUME_HIGH

    @property
    def native_value(self) -> float | None:
        """Return current alarm volume percentage (0-100)."""
        device = self.get_device()
        if not device:
            return None
        vol = device.get_alarm_volume()
        if vol is not None:
            return vol
        # Fallback to general device volume if alarm volume not polled yet
        dev_vol = device.get_device_volume()
        if dev_vol is not None:
            return dev_vol
        return 50.0

    async def async_set_native_value(self, value: float) -> None:
        """Set alarm volume percentage on the device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        vol_int = int(round(value))
        device.set_alarm_volume(vol_int)
        await self.client.update_alarm_volume(device=device, volume=vol_int)
        self.async_write_ha_state()


class GoogleHomeDeviceVolumeNumber(GoogleHomeBaseEntity, NumberEntity):
    """Google Home Media/Speaker Volume slider entity."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "%"

    @property
    def label(self) -> str:
        """Label to use for unique_id and name."""
        return "volume"

    @property
    def icon(self) -> str:
        """Dynamically return volume icon based on current volume level."""
        val = self.native_value
        if val is None or val == 0:
            return ICON_ALARM_VOLUME_OFF
        if val < 33:
            return ICON_ALARM_VOLUME_LOW
        if val < 66:
            return ICON_ALARM_VOLUME_MID
        return ICON_ALARM_VOLUME_HIGH

    @property
    def native_value(self) -> float | None:
        """Return current media volume percentage (0-100)."""
        device = self.get_device()
        if not device:
            return None
        vol = device.get_device_volume()
        if vol is not None:
            return vol
        alarm_vol = device.get_alarm_volume()
        if alarm_vol is not None:
            return alarm_vol
        return 50.0

    async def async_set_native_value(self, value: float) -> None:
        """Set media/speaker volume percentage on the device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        vol_int = int(round(value))
        device.set_device_volume(vol_int)

        local_success = False
        # 1. Local HTTP command
        try:
            res = await self.client.update_device_volume(device=device, volume=vol_int)
            local_success = res is not None
        except Exception as err:
            _LOGGER.debug(
                "Local update_device_volume failed on %s: %s", self.device_name, err
            )

        # 2. Assistant SDK fallback ONLY on failure if enabled in config entry options
        if not local_success:
            config_entry = getattr(self.coordinator, "config_entry", None)
            third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
            if config_entry:
                third_party_mode = config_entry.options.get(
                    CONF_THIRD_PARTY_ENTITY_MODE,
                    config_entry.data.get(
                        CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                    ),
                )

            if (
                third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK
                and self.hass.services.has_service(
                    "google_assistant_sdk", "send_text_command"
                )
            ):
                try:
                    cmd = format_command(
                        self.hass, "set_volume", self.device_name, volume=vol_int
                    )
                    await self.hass.services.async_call(
                        "google_assistant_sdk",
                        "send_text_command",
                        {"command": cmd},
                        blocking=False,
                    )
                except Exception as ex:
                    _LOGGER.debug("Assistant SDK volume fallback error: %s", ex)

        self.async_write_ha_state()
