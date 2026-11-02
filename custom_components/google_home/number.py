"""Number platform for Google Home."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import TrackStates, async_track_state_change_filtered

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
from .volume import volume_percentage

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
            self._restored_value = volume_percentage(last_state.state, normalized=False)

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
            return self._restored_value

        vol = device.get_alarm_volume()
        if vol is not None:
            return vol

        return self._restored_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Identify historical alarm values without using media volume as a fallback."""
        device = self.get_device()
        live = device.get_alarm_volume() if device else None
        return {
            "volume_source": "local_alarm"
            if live is not None
            else ("restored" if self._restored_value is not None else "unknown"),
            "restored_volume": self._restored_value,
        }

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
        self._last_media_player_entity_id: str | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added to Home Assistant."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            self._restored_value = volume_percentage(last_state.state, normalized=False)

        tracker = async_track_state_change_filtered(
            self.hass,
            TrackStates(all_states=False, entities=set(), domains={"media_player"}),
            self._async_cast_state_changed,
        )
        self.async_on_remove(tracker.async_remove)

    @callback
    def _async_cast_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Refresh when Cast arrives after startup or changes its live volume."""
        entity_id = event.data["entity_id"]
        if entity_id in (
            self._last_media_player_entity_id,
            self._find_target_media_player(),
        ):
            self.async_write_ha_state()

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
        """Prefer Cast identity/device links; use only exact, unambiguous name matches."""
        # Volume telemetry does not require PLAY_MEDIA. Assistant volume commands
        # use the device name and do not pass a playback target to the SDK.
        dev_name = self.device_name.strip().lower()
        dev_slug = dev_name.replace(" ", "_")
        registry = er.async_get(self.hass)
        own_entry = registry.async_get(self.entity_id) if self.entity_id else None
        device = self.get_device()
        cast_uuid = (device.cast_uuid or "").replace("-", "").lower() if device else ""
        candidates: list[str] = []
        for state in self.hass.states.async_all("media_player"):
            entry = registry.async_get(state.entity_id)
            if entry is None or entry.platform != "cast":
                continue
            if cast_uuid and entry.unique_id.replace("-", "").lower() == cast_uuid:
                return state.entity_id
            if (
                own_entry
                and own_entry.device_id
                and entry.device_id == own_entry.device_id
            ):
                return state.entity_id
            fname = state.attributes.get("friendly_name", "").strip().lower()
            if fname == dev_name or state.entity_id == f"media_player.{dev_slug}":
                candidates.append(state.entity_id)
        return candidates[0] if len(candidates) == 1 else None

    def _cast_volume(self) -> tuple[float | None, str | None]:
        """Return an available Cast reading, never a restored media player state."""
        target_mp = self._find_target_media_player()
        if target_mp:
            self._last_media_player_entity_id = target_mp
            state = self.hass.states.get(target_mp)
            if (
                state
                and state.state not in ("unknown", "unavailable")
                and not state.attributes.get("restored")
            ):
                return volume_percentage(
                    state.attributes.get("volume_level"), normalized=True
                ), target_mp
        return None, target_mp

    def _volume_reading(self) -> tuple[float | None, str]:
        """Use only local Cast/device telemetry, then explicitly labelled history."""
        cast_volume, _ = self._cast_volume()
        if cast_volume is not None:
            return cast_volume, "google_cast"
        device = self.get_device()
        if device and device.get_device_volume() is not None:
            return (
                device.get_device_volume(),
                device.device_volume_source or "local_api",
            )

        if self._restored_value is not None:
            return self._restored_value, "restored"
        return None, "unknown"

    @property
    def native_value(self) -> float | None:
        """Return current media volume percentage (0-100)."""
        return self._volume_reading()[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose volume provenance for startup and live-observation diagnostics."""
        device = self.get_device()
        cast_volume, target = self._cast_volume()
        state = self.hass.states.get(target) if target else None
        if cast_volume is not None:
            cast_status = "ready"
        elif state is None:
            cast_status = "not_found"
        elif state.state in ("unknown", "unavailable"):
            cast_status = state.state
        elif state.attributes.get("restored"):
            cast_status = "restored"
        else:
            cast_status = "volume_missing"
        return {
            "volume_source": self._volume_reading()[1],
            "cast_volume": cast_volume,
            "local_volume": device.get_device_volume() if device else None,
            "direct_cast_status": device.direct_cast_status
            if device
            else "missing_device",
            "restored_volume": self._restored_value,
            "media_player_entity_id": target,
            "cast_status": cast_status,
            "cast_integration_loaded": "cast" in self.hass.config.components,
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set media/speaker volume percentage on the device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        vol_int = int(round(value))
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
