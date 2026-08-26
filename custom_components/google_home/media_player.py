"""Media Player platform for Google Home Cloud devices (TVs, Soundbars, Receivers)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .cloud_models import CloudHomeDevice
from .const import DATA_CLOUD_COORDINATOR, DOMAIN, MANUFACTURER

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Google Home media player entities."""
    if (
        DOMAIN not in hass.data
        or entry.entry_id not in hass.data[DOMAIN]
        or DATA_CLOUD_COORDINATOR not in hass.data[DOMAIN][entry.entry_id]
    ):
        return True

    coordinator: GoogleHomeCloudDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_CLOUD_COORDINATOR]

    registered_ids: set[str] = set()

    def _create_entities() -> list[GoogleHomeCloudMediaPlayer]:
        new_ents = []
        for dev in coordinator.data or []:
            if dev.is_media_player and dev.device_id not in registered_ids:
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudMediaPlayer(
                        coordinator=coordinator, device_id=dev.device_id
                    )
                )
        return new_ents

    entities = _create_entities()
    if entities:
        async_add_entities(entities)

    @callback
    def _async_add_new_devices() -> None:
        new_devices = _create_entities()
        if new_devices:
            async_add_entities(new_devices)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))
    return True


class GoogleHomeCloudMediaPlayer(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], MediaPlayerEntity
):
    """Representation of a Google Home Cloud Media Player (TV / Soundbar)."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize cloud media player entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"google_home_cloud_media_{device_id}"

    def get_cloud_device(self) -> CloudHomeDevice | None:
        """Return device model from coordinator data."""
        for dev in self.coordinator.data or []:
            if dev.device_id == self._device_id:
                return dev
        return None

    @property
    def name(self) -> str:
        """Return friendly name."""
        cdev = self.get_cloud_device()
        return cdev.name if cdev else "Google Media Player"

    @property
    def available(self) -> bool:
        """Return True if device is online."""
        cdev = self.get_cloud_device()
        return cdev.online if cdev else False

    @property
    def device_class(self) -> MediaPlayerDeviceClass:
        """Return device class based on type."""
        cdev = self.get_cloud_device()
        if not cdev:
            return MediaPlayerDeviceClass.SPEAKER
        dtype = cdev.device_type.upper()
        if "TV" in dtype or "SETTOP" in dtype:
            return MediaPlayerDeviceClass.TV
        if "RECEIVER" in dtype:
            return MediaPlayerDeviceClass.RECEIVER
        return MediaPlayerDeviceClass.SPEAKER

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features."""
        features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
        )
        return features

    @property
    def state(self) -> MediaPlayerState | None:
        """Return playback state."""
        cdev = self.get_cloud_device()
        if not cdev or not cdev.online:
            return MediaPlayerState.OFF
        if "on" in cdev.state and not cdev.state["on"]:
            return MediaPlayerState.OFF
        activity = cdev.state.get("activityState", "").upper()
        if activity in ("PLAYING", "ACTIVE"):
            return MediaPlayerState.PLAYING
        if activity in ("PAUSED", "STANDBY"):
            return MediaPlayerState.PAUSED
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        """Return volume level (0.0 to 1.0)."""
        cdev = self.get_cloud_device()
        if not cdev:
            return None
        v = cdev.state.get("currentVolume", cdev.state.get("volume"))
        if v is not None:
            try:
                fv = float(v)
                return fv / 100 if fv > 1.0 else fv
            except (ValueError, TypeError):
                pass
        return None

    @property
    def is_volume_muted(self) -> bool | None:
        """Return True if volume is muted."""
        cdev = self.get_cloud_device()
        if not cdev:
            return None
        return bool(cdev.state.get("isMuted", False))

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        cdev = self.get_cloud_device()
        manufacturer = cdev.manufacturer if cdev else MANUFACTURER
        model = cdev.model_name if cdev else "Cloud Media Player"
        sw_version = cdev.firmware_version if cdev else None
        hw_version = cdev.hardware_version if cdev else None
        suggested_area = cdev.room_name if cdev else None

        connections = set()
        if cdev and cdev.mac_address:
            from homeassistant.helpers.device_registry import (
                CONNECTION_NETWORK_MAC,
                format_mac,
            )

            connections.add((CONNECTION_NETWORK_MAC, format_mac(cdev.mac_address)))

        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self.name,
            manufacturer=manufacturer,
            model=model,
            sw_version=sw_version,
            hw_version=hw_version,
            suggested_area=suggested_area,
            connections=connections,
            configuration_url="https://home.google.com/",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional media player attributes."""
        cdev = self.get_cloud_device()
        if not cdev:
            return {}
        return {
            "device_type": cdev.device_type,
            "traits": cdev.traits,
            "structure": cdev.structure_name,
            "room": cdev.room_name,
            "agent": cdev.agent_name or cdev.agent_id,
        }

    async def async_turn_on(self) -> None:
        """Turn on the media player."""
        cdev = self.get_cloud_device()
        if cdev:
            cdev.state["on"] = True
            await self.coordinator.cloud_client.async_execute_command(
                self._device_id,
                "action.devices.commands.OnOff",
                {"on": True},
            )
            self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn off the media player."""
        cdev = self.get_cloud_device()
        if cdev:
            cdev.state["on"] = False
            await self.coordinator.cloud_client.async_execute_command(
                self._device_id,
                "action.devices.commands.OnOff",
                {"on": False},
            )
            self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level."""
        cdev = self.get_cloud_device()
        pct = int(round(volume * 100))
        if cdev:
            cdev.state["currentVolume"] = pct

        # 1. Direct local speaker control (zero latency & 100% working)
        config_entry = getattr(self.coordinator, "config_entry", None)
        entry_id = getattr(config_entry, "entry_id", None) if config_entry else None
        if entry_id and entry_id in self.hass.data.get(DOMAIN, {}):
            entry_data = self.hass.data[DOMAIN][entry_id]
            local_client = entry_data.get("client")
            local_coord = entry_data.get("coordinator")
            if local_coord and local_client and cdev:
                for ldev in local_coord.data or []:
                    if ldev.name.lower() == cdev.name.lower() or (
                        ldev.device_id and ldev.device_id == cdev.device_id
                    ):
                        await local_client.update_device_volume(ldev, pct)
                        break

        # 2. Cloud execute command fallback
        await self.coordinator.cloud_client.async_execute_command(
            self._device_id,
            "action.devices.commands.setVolume",
            {"volumeLevel": pct},
        )
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        cdev = self.get_cloud_device()
        if cdev:
            cdev.state["isMuted"] = mute
            await self.coordinator.cloud_client.async_execute_command(
                self._device_id,
                "action.devices.commands.mute",
                {"mute": mute},
            )
            self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Play media."""
        await self.coordinator.cloud_client.async_execute_command(
            self._device_id,
            "action.devices.commands.mediaResume",
            {},
        )

    async def async_media_pause(self) -> None:
        """Pause media."""
        await self.coordinator.cloud_client.async_execute_command(
            self._device_id,
            "action.devices.commands.mediaPause",
            {},
        )
