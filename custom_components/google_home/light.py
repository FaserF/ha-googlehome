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
            if dev.device_id in registered_ids:
                continue

            is_nightlight_dev = (
                "action.devices.traits.NightLight" in (dev.traits or [])
                or "action.devices.types.NIGHTLIGHT" in (dev.traits or [])
                or any(
                    k in (dev.hardware_model or "").lower() or k in dev.name.lower()
                    for k in ("clock", "uhr", "cd-")
                )
            )

            should_add = False
            if is_nightlight_dev:
                should_add = third_party_mode != THIRD_PARTY_MODE_READONLY
            elif dev.is_light:
                should_add = (
                    not dev.is_third_party
                    or third_party_mode != THIRD_PARTY_MODE_READONLY
                )

            if should_add:
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
        device = self.get_device()
        is_nightlight = device and (
            "action.devices.traits.NightLight" in (device.traits or [])
            or "action.devices.types.NIGHTLIGHT" in (device.traits or [])
            or any(
                k in (device.hardware_model or "").lower() or k in device.name.lower()
                for k in ("clock", "uhr", "cd-")
            )
        )
        traits = device.traits if device and device.traits else []
        has_color = (
            "action.devices.traits.ColorSetting" in traits
            or "action.devices.traits.Color" in traits
            or "color" in getattr(device, "attributes", {})
        )
        has_brightness = (
            "action.devices.traits.Brightness" in traits
            or "brightness" in getattr(device, "attributes", {})
            or has_color
        )

        self._is_nightlight = bool(is_nightlight)
        modes = set()
        if is_nightlight:
            modes.add(ColorMode.BRIGHTNESS)
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_icon = "mdi:lightbulb-night-outline"
            self._attr_has_entity_name = True
            self._attr_translation_key = "nightlight"
        elif has_color:
            modes.add(ColorMode.RGB)
            modes.add(ColorMode.COLOR_TEMP)
            self._attr_color_mode = ColorMode.RGB
        elif has_brightness:
            modes.add(ColorMode.BRIGHTNESS)
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            modes.add(ColorMode.ONOFF)
            self._attr_color_mode = ColorMode.ONOFF

        self._attr_supported_color_modes = modes

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str | None:
        """Return name."""
        if self._is_nightlight:
            return None
        device = self.get_device()
        return device.name if device else "Google Light"

    @property
    def is_on(self) -> bool:
        """Return on status."""
        device = self.get_device()
        if not device:
            return False
        if self._is_nightlight:
            return bool(device.state.get("nightlight_on", False))
        return bool(device.state.get("on", False))

    @property
    def brightness(self) -> int | None:
        """Return brightness (0-255)."""
        device = self.get_device()
        if not device or not self.is_on:
            return None
        bri_pct = device.state.get("brightness")
        if bri_pct is not None:
            try:
                return int(round(float(bri_pct) * 255 / 100))
            except (ValueError, TypeError):
                pass
        return 255

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the rgb color value [int, int, int]."""
        device = self.get_device()
        if not device or not self.is_on:
            return None
        c_state = device.state.get("color")
        if isinstance(c_state, dict) and "spectrumRGB" in c_state:
            rgb_int = int(c_state["spectrumRGB"])
            return (
                (rgb_int >> 16) & 255,
                (rgb_int >> 8) & 255,
                rgb_int & 255,
            )
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        device = self.get_device()
        if not device or not self.is_on:
            return None
        c_state = device.state.get("color")
        if isinstance(c_state, dict) and "temperatureK" in c_state:
            return int(c_state["temperatureK"])
        return None

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

    def _find_target_media_player(self) -> str | None:
        """Find matching media_player entity for this device in Home Assistant."""
        device = self.get_device()
        if not device:
            return None

        dev_name = device.name.strip().lower()
        dev_slug = dev_name.replace(" ", "_")

        # 1. Search for matching entity_id in hass states
        for state in self.hass.states.async_all("media_player"):
            if dev_slug in state.entity_id:
                return state.entity_id
            fname = state.attributes.get("friendly_name", "").strip().lower()
            if fname == dev_name:
                return state.entity_id

        return None

    async def _async_send_assistant_command(
        self, command: str, target_media_player: bool = False
    ) -> None:
        """Forward command via Google Assistant SDK with optional media_player target."""
        if self.hass.services.has_service("google_assistant_sdk", "send_text_command"):
            try:
                service_data: dict[str, Any] = {"command": command}
                if target_media_player:
                    target_mp = self._find_target_media_player()
                    if target_mp:
                        service_data["media_player"] = target_mp

                _LOGGER.debug(
                    "Sending Assistant SDK command: %s (data=%s)", command, service_data
                )
                await self.hass.services.async_call(
                    "google_assistant_sdk",
                    "send_text_command",
                    service_data,
                    blocking=False,
                )
            except Exception as ex:
                _LOGGER.warning("Error invoking google_assistant_sdk: %s", ex)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        device = self.get_device()
        brightness = kwargs.get("brightness")
        is_nightlight = device and (
            "action.devices.traits.NightLight" in (device.traits or [])
            or any(
                k in (device.hardware_model or "").lower() or k in device.name.lower()
                for k in ("clock", "uhr", "cd-")
            )
        )
        if device:
            if is_nightlight:
                device.state["nightlight_on"] = True
            else:
                device.state["on"] = True
            if brightness is not None:
                device.state["brightness"] = int(round(brightness * 100 / 255))

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        rgb_color = kwargs.get("rgb_color")
        color_temp = kwargs.get("color_temp_kelvin") or kwargs.get("color_temp")

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK and device:
            dev_name = device.name
            target_mp = self._find_target_media_player()
            if is_nightlight:
                if brightness is not None:
                    pct = int(round(brightness * 100 / 255))
                    action = "set_nightlight" if target_mp else "set_nightlight_named"
                    cmd = format_command(
                        self.hass,
                        action,
                        dev_name,
                        brightness=pct,
                    )
                    await self._async_send_assistant_command(
                        cmd, target_media_player=True
                    )
                else:
                    action = (
                        "turn_on_nightlight"
                        if target_mp
                        else "turn_on_nightlight_named"
                    )
                    cmd = format_command(
                        self.hass,
                        action,
                        dev_name,
                    )
                    await self._async_send_assistant_command(
                        cmd, target_media_player=True
                    )

            else:
                was_off = not self.is_on
                # 1. Color (RGB)
                if rgb_color is not None:
                    if was_off:
                        await self._async_send_assistant_command(
                            format_command(self.hass, "turn_on", dev_name)
                        )
                    r, g, b = rgb_color
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                    await self._async_send_assistant_command(
                        format_command(
                            self.hass, "set_color", dev_name, color=hex_color
                        )
                    )

                # 2. Color Temperature (Kelvin)
                elif color_temp is not None:
                    if was_off:
                        await self._async_send_assistant_command(
                            format_command(self.hass, "turn_on", dev_name)
                        )
                    kelvin = (
                        int(color_temp)
                        if color_temp > 1000
                        else int(round(1000000 / color_temp))
                    )
                    await self._async_send_assistant_command(
                        format_command(
                            self.hass, "set_color_temp", dev_name, kelvin=kelvin
                        )
                    )

                # 3. Brightness
                if brightness is not None:
                    pct = int(round(brightness * 100 / 255))
                    await self._async_send_assistant_command(
                        format_command(
                            self.hass, "set_brightness", dev_name, brightness=pct
                        )
                    )
                elif rgb_color is None and color_temp is None:
                    await self._async_send_assistant_command(
                        format_command(self.hass, "turn_on", dev_name)
                    )

        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD and device:
            if "action.devices.traits.NightLight" in (device.traits or []):
                await self.coordinator.client.async_execute_command(
                    device_id=self.device_id,
                    command="action.devices.commands.SetNightLight",
                    params={"on": True},
                )
            else:
                params: dict[str, Any] = {"on": True}
                if brightness is not None:
                    params["brightness"] = int(round(brightness * 100 / 255))
                await self.coordinator.client.async_execute_command(
                    device_id=self.device_id,
                    command="action.devices.commands.OnOff",
                    params=params,
                )

        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        device = self.get_device()
        is_nightlight = device and (
            "action.devices.traits.NightLight" in (device.traits or [])
            or any(
                k in (device.hardware_model or "").lower() or k in device.name.lower()
                for k in ("clock", "uhr", "cd-")
            )
        )
        if device:
            if is_nightlight:
                device.state["nightlight_on"] = False
            else:
                device.state["on"] = False

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
            dev_name = device.name
            target_mp = self._find_target_media_player()
            if is_nightlight:
                action = (
                    "turn_off_nightlight" if target_mp else "turn_off_nightlight_named"
                )
                cmd = format_command(
                    self.hass,
                    action,
                    dev_name,
                )
                await self._async_send_assistant_command(cmd, target_media_player=True)
            else:
                await self._async_send_assistant_command(
                    format_command(self.hass, "turn_off", dev_name)
                )

        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD and device:
            if "action.devices.traits.NightLight" in (device.traits or []):
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
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()
