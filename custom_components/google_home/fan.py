"""Fan platform for Google Home Cloud devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    ranged_value_to_percentage,
)

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
    """Set up Google Home fan entities."""
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

    def _create_entities() -> list[GoogleHomeCloudFan]:
        new_ents = []
        for dev in coordinator.data or []:
            if (
                dev.is_fan
                and dev.device_id not in registered_ids
                and (
                    not dev.is_third_party
                    or third_party_mode != THIRD_PARTY_MODE_READONLY
                )
            ):
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudFan(coordinator=coordinator, device_id=dev.device_id)
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


class GoogleHomeCloudFan(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], FanEntity
):
    """Representation of a Google Home Cloud Fan / Air Purifier."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize cloud fan entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"google_home_cloud_fan_{device_id}"

    def get_cloud_device(self) -> CloudHomeDevice | None:
        """Return the device model from coordinator data."""
        for dev in self.coordinator.data or []:
            if dev.device_id == self._device_id:
                return dev
        return None

    @property
    def name(self) -> str:
        """Return the friendly name of the fan."""
        cdev = self.get_cloud_device()
        return cdev.name if cdev else "Google Fan"

    @property
    def available(self) -> bool:
        """Return True if device is available in HomeGraph."""
        cdev = self.get_cloud_device()
        return cdev.online if cdev else False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information linking to device registry."""
        cdev = self.get_cloud_device()
        manufacturer = cdev.manufacturer if cdev else MANUFACTURER
        model = cdev.model_name if cdev else "Cloud Fan"
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
            configuration_url=get_structure_url(
                cdev.structure_id if cdev else None, "devices"
            ),
        )

    @property
    def supported_features(self) -> FanEntityFeature:
        """Return supported fan features."""
        features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        cdev = self.get_cloud_device()
        if not cdev:
            return features

        traits = cdev.traits or []
        if (
            "action.devices.traits.FanSpeed" in traits
            or "currentFanSpeedPercent" in cdev.state
            or "fanSpeedPercent" in cdev.state
            or "speed" in cdev.state
        ):
            features |= FanEntityFeature.SET_SPEED
            features |= FanEntityFeature.PRESET_MODE

        # Smart fans like Xiaomi / Dyson with FanSpeed also support oscillation and direction in HomeGraph
        if (
            "action.devices.traits.Oscillation" in traits
            or "action.devices.traits.FanSpeed" in traits
            or "isOscillating" in cdev.state
        ):
            features |= FanEntityFeature.OSCILLATE

        if (
            "action.devices.traits.Reverse" in traits
            or "action.devices.traits.FanSpeed" in traits
            or "fanDirection" in cdev.state
        ):
            features |= FanEntityFeature.DIRECTION

        return features

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports (e.g. 4 for Level1-Level4)."""
        cdev = self.get_cloud_device()
        if not cdev:
            return 100
        avail = cdev.attributes.get("availableFanSpeeds")
        if isinstance(avail, dict) and "speeds" in avail and avail["speeds"]:
            return len(avail["speeds"])
        return 4

    @property
    def preset_modes(self) -> list[str] | None:
        """Return available preset speed modes (e.g. Level 1, Level 2, Level 3, Level 4)."""
        return ["Level 1", "Level 2", "Level 3", "Level 4", "Auto", "Nature"]

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        cdev = self.get_cloud_device()
        if not cdev:
            return None
        pct = self.percentage
        if pct is not None:
            if pct <= 25:
                return "Level 1"
            if pct <= 50:
                return "Level 2"
            if pct <= 75:
                return "Level 3"
            return "Level 4"
        return str(cdev.state.get("currentFanSpeedSetting", "Level 1"))

    @property
    def is_on(self) -> bool | None:
        """Return True if fan is on."""
        cdev = self.get_cloud_device()
        if not cdev:
            return None
        # Check standard on/off state
        if "on" in cdev.state:
            return bool(cdev.state["on"])
        if "is_on" in cdev.state:
            return bool(cdev.state["is_on"])
        if "currentFanSpeedPercent" in cdev.state:
            return float(cdev.state["currentFanSpeedPercent"]) > 0
        return False

    @property
    def percentage(self) -> int | None:
        """Return current speed percentage (0-100)."""
        cdev = self.get_cloud_device()
        if not cdev:
            return None
        # Percentage directly in state
        pct = cdev.state.get(
            "currentFanSpeedPercent", cdev.state.get("fanSpeedPercent")
        )
        if pct is not None:
            try:
                return int(round(float(pct)))
            except (ValueError, TypeError):
                pass
        # Numeric speed level mapping
        speed = cdev.state.get("currentFanSpeedSetting", cdev.state.get("speed"))
        if speed is not None:
            try:
                sp_num = float(speed)
                max_speed = 100.0
                avail = cdev.attributes.get("availableFanSpeeds")
                if isinstance(avail, dict) and "speeds" in avail and avail["speeds"]:
                    max_speed = float(len(avail["speeds"]))
                return int(round(ranged_value_to_percentage((1, max_speed), sp_num)))
            except Exception:
                pass
        return None

    @property
    def oscillating(self) -> bool | None:
        """Return whether fan is oscillating."""
        cdev = self.get_cloud_device()
        if not cdev:
            return None
        return (
            bool(cdev.state.get("isOscillating", False))
            if "isOscillating" in cdev.state
            else None
        )

    @property
    def current_direction(self) -> str | None:
        """Return current fan direction."""
        cdev = self.get_cloud_device()
        if not cdev:
            return None
        direction = cdev.state.get("fanDirection")
        return str(direction).lower() if direction else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional diagnostic fan attributes."""
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

    async def _async_send_assistant_command(self, command: str) -> None:
        """Forward command via Google Assistant SDK if installed and available."""
        if self.hass.services.has_service("google_assistant_sdk", "send_text_command"):
            try:
                _LOGGER.debug("Sending Assistant SDK fan command: %s", command)
                await self.hass.services.async_call(
                    "google_assistant_sdk",
                    "send_text_command",
                    {"command": command},
                    blocking=False,
                )
            except Exception as ex:
                _LOGGER.warning("Error invoking google_assistant_sdk: %s", ex)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        already_on = self.is_on
        cdev.state["on"] = True
        cdev.state["is_on"] = True
        if percentage is not None:
            cdev.state["currentFanSpeedPercent"] = percentage

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK:
            dev_name = cdev.name
            if percentage is not None:
                await self._async_send_assistant_command(
                    f"Set fan speed on {dev_name} to {percentage}%"
                )
            elif not already_on:
                await self._async_send_assistant_command(f"Turn on {dev_name}")
        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD:
            if percentage is not None:
                await self.coordinator.cloud_client.async_execute_command(
                    self._device_id,
                    "action.devices.commands.SetFanSpeed",
                    {"fanSpeedPercent": percentage},
                )
            else:
                await self.coordinator.cloud_client.async_execute_command(
                    self._device_id,
                    "action.devices.commands.OnOff",
                    {"on": True},
                )
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        already_off = not self.is_on
        cdev.state["on"] = False
        cdev.state["is_on"] = False

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK:
            if not already_off:
                await self._async_send_assistant_command(
                    format_command(self.hass, "turn_off", cdev.name)
                )
        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD:
            await self.coordinator.cloud_client.async_execute_command(
                self._device_id,
                "action.devices.commands.OnOff",
                {"on": False},
            )
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set fan speed percentage."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        if percentage == 0:
            await self.async_turn_off()
            return

        was_off = not self.is_on
        cdev.state["on"] = True
        cdev.state["is_on"] = True
        cdev.state["currentFanSpeedPercent"] = percentage

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK:
            if was_off:
                await self._async_send_assistant_command(
                    format_command(self.hass, "turn_on", cdev.name)
                )
            await self._async_send_assistant_command(
                format_command(
                    self.hass, "set_fan_speed", cdev.name, percentage=percentage
                )
            )
        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD:
            await self.coordinator.cloud_client.async_execute_command(
                self._device_id,
                "action.devices.commands.SetFanSpeed",
                {"fanSpeedPercent": percentage},
            )
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    async def async_oscillate(self, oscillating: bool) -> None:
        """Set fan oscillation."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        cdev.state["isOscillating"] = oscillating

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK:
            action = (
                "turn_on_fan_oscillation" if oscillating else "turn_off_fan_oscillation"
            )
            cmd = format_command(self.hass, action, cdev.name)
            await self._async_send_assistant_command(cmd)

        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD:
            await self.coordinator.cloud_client.async_execute_command(
                self._device_id,
                "action.devices.commands.SetOscillation",
                {"oscillate": oscillating},
            )
        self.async_write_ha_state()

    async def async_set_direction(self, direction: str) -> None:
        """Set fan rotation direction."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        cdev.state["fanDirection"] = direction

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK:
            await self._async_send_assistant_command(
                format_command(
                    self.hass, "set_fan_direction", cdev.name, direction=direction
                )
            )
        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD:
            await self.coordinator.cloud_client.async_execute_command(
                self._device_id,
                "action.devices.commands.SetFanDirection",
                {"direction": direction},
            )
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        mode_pct_map = {
            "Level 1": 25,
            "Level 2": 50,
            "Level 3": 75,
            "Level 4": 100,
            "Auto": 50,
            "Nature": 30,
        }
        pct = mode_pct_map.get(preset_mode, 50)
        cdev.state["on"] = True
        cdev.state["currentFanSpeedPercent"] = pct
        cdev.state["currentFanSpeedSetting"] = preset_mode

        config_entry = getattr(self.coordinator, "config_entry", None)
        third_party_mode = DEFAULT_THIRD_PARTY_ENTITY_MODE
        if config_entry:
            third_party_mode = config_entry.options.get(
                CONF_THIRD_PARTY_ENTITY_MODE,
                config_entry.data.get(
                    CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
                ),
            )

        if third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK:
            await self._async_send_assistant_command(
                format_command(
                    self.hass, "set_fan_preset", cdev.name, preset=preset_mode
                )
            )
        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD:
            await self.coordinator.cloud_client.async_execute_command(
                self._device_id,
                "action.devices.commands.SetFanSpeed",
                {"fanSpeed": preset_mode, "fanSpeedPercent": pct},
            )
        self.async_write_ha_state()
