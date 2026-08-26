"""Number platform for Google Home."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_COORDINATOR,
    DOMAIN,
    ICON_ALARM_VOLUME_HIGH,
    ICON_ALARM_VOLUME_LOW,
    ICON_ALARM_VOLUME_MID,
    ICON_ALARM_VOLUME_OFF,
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
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
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
        return 40.0

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
    """Google Home Speaker Live Media/Speech Volume slider entity."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
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
        """Return current speaker volume percentage (0-100)."""
        device = self.get_device()
        if not device:
            return None

        # 1. Use cached device volume if set
        vol = device.get_device_volume()
        if vol is not None:
            return vol

        # 2. Bridge with Home Assistant media_player entity for live Cast speaker volume
        dname = self.device_name.strip().lower()
        slug = dname.replace(" ", "_")
        for state in self.hass.states.async_all("media_player"):
            fname = state.attributes.get("friendly_name", "").strip().lower()
            if (
                fname == dname or slug in state.entity_id
            ) and "volume_level" in state.attributes:
                vlevel = state.attributes.get("volume_level")
                if vlevel is not None:
                    return round(float(vlevel) * 100)

        return 50.0

    async def async_set_native_value(self, value: float) -> None:
        """Set normal speaker volume percentage on the device with instant live sync."""
        device = self.get_device()
        if device is not None:
            device.set_device_volume(value)

        vol_int = int(round(value))
        float_val = round(value / 100, 2)

        # 1. Sync via local API if available
        if device is not None:
            try:
                await self.client.update_device_volume(device=device, volume=vol_int)
            except Exception:
                pass

        # 2. Sync directly with Home Assistant media_player entity for immediate speaker volume change
        dname = self.device_name.strip().lower()
        slug = dname.replace(" ", "_")
        for state in self.hass.states.async_all("media_player"):
            fname = state.attributes.get("friendly_name", "").strip().lower()
            if fname == dname or slug in state.entity_id:
                await self.hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": state.entity_id, "volume_level": float_val},
                    blocking=False,
                )

        self.async_write_ha_state()
