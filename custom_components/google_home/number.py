"""Number platform for Google Home."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .assistant_helper import format_command
from .const import (
    CONF_THIRD_PARTY_ENTITY_MODE,
    DATA_CLOUD_COORDINATOR,
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


class GoogleHomeAlarmVolumeNumber(GoogleHomeBaseEntity, RestoreNumber):
    """Google Home Alarm Volume slider entity."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "%"

    def __init__(
        self,
        coordinator: GoogleHomeDataUpdateCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, device_id, device_name)
        self._restored_value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added to Home Assistant."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            try:
                self._restored_value = float(last_state.state)
                device = self.get_device()
                if device and device.get_alarm_volume() is None:
                    device.set_alarm_volume(self._restored_value)
            except (ValueError, TypeError):
                pass

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

    @property
    def native_value(self) -> float | None:
        """Return current alarm volume percentage (0-100)."""
        device = self.get_device()
        if not device:
            return self._restored_value

        vol = device.get_alarm_volume()
        if vol is not None:
            return vol

        dev_vol = device.get_device_volume()
        if dev_vol is not None:
            return dev_vol

        # Check matched media_player entity volume in Home Assistant
        target_mp = self._find_target_media_player()
        if target_mp:
            mp_state = self.hass.states.get(target_mp)
            if mp_state and "volume_level" in mp_state.attributes:
                vlevel = mp_state.attributes.get("volume_level")
                if vlevel is not None:
                    return round(float(vlevel) * 100)

        # Check corresponding CloudHomeDevice in cloud coordinator if available
        entry_data = self.hass.data.get(DOMAIN, {}).get(
            getattr(self.coordinator.config_entry, "entry_id", ""), {}
        )
        cloud_coord = entry_data.get(DATA_CLOUD_COORDINATOR)
        if cloud_coord and cloud_coord.data:
            for cdev in cloud_coord.data:
                if (
                    cdev.device_id == self.device_id
                    or cdev.name.lower() == self.device_name.lower()
                ):
                    cloud_v = cdev.state.get("currentVolume", cdev.state.get("volume"))
                    if cloud_v is not None:
                        try:
                            cfv = float(cloud_v)
                            return cfv if cfv > 1.0 else cfv * 100
                        except (ValueError, TypeError):
                            pass

        if self._restored_value is not None:
            return self._restored_value

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set alarm volume percentage on the device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        vol_int = int(round(value))
        self._restored_value = float(vol_int)
        device.set_alarm_volume(vol_int)
        await self.client.update_alarm_volume(device=device, volume=vol_int)
        self.async_write_ha_state()


class GoogleHomeDeviceVolumeNumber(GoogleHomeBaseEntity, RestoreNumber):
    """Google Home Media/Speaker Volume slider entity."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "%"

    def __init__(
        self,
        coordinator: GoogleHomeDataUpdateCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, device_id, device_name)
        self._restored_value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added to Home Assistant."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            try:
                self._restored_value = float(last_state.state)
                device = self.get_device()
                if device and device.get_device_volume() is None:
                    device.set_device_volume(self._restored_value)
            except (ValueError, TypeError):
                pass

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

    @property
    def native_value(self) -> float | None:
        """Return current media volume percentage (0-100)."""
        device = self.get_device()
        if not device:
            return self._restored_value

        vol = device.get_device_volume()
        if vol is not None:
            return vol

        alarm_vol = device.get_alarm_volume()
        if alarm_vol is not None:
            return alarm_vol

        # Check matched media_player entity volume in Home Assistant
        target_mp = self._find_target_media_player()
        if target_mp:
            mp_state = self.hass.states.get(target_mp)
            if mp_state and "volume_level" in mp_state.attributes:
                vlevel = mp_state.attributes.get("volume_level")
                if vlevel is not None:
                    return round(float(vlevel) * 100)

        # Check corresponding CloudHomeDevice in cloud coordinator if available
        entry_data = self.hass.data.get(DOMAIN, {}).get(
            getattr(self.coordinator.config_entry, "entry_id", ""), {}
        )
        cloud_coord = entry_data.get(DATA_CLOUD_COORDINATOR)
        if cloud_coord and cloud_coord.data:
            for cdev in cloud_coord.data:
                if (
                    cdev.device_id == self.device_id
                    or cdev.name.lower() == self.device_name.lower()
                ):
                    cloud_v = cdev.state.get("currentVolume", cdev.state.get("volume"))
                    if cloud_v is not None:
                        try:
                            cfv = float(cloud_v)
                            return cfv if cfv > 1.0 else cfv * 100
                        except (ValueError, TypeError):
                            pass

        if self._restored_value is not None:
            return self._restored_value

        return None

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
