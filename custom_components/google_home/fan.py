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

from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .cloud_models import CloudHomeDevice
from .const import DATA_CLOUD_COORDINATOR, DOMAIN, MANUFACTURER

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

    registered_ids: set[str] = set()

    def _create_entities() -> list[GoogleHomeCloudFan]:
        new_ents = []
        for dev in coordinator.data or []:
            if dev.is_fan and dev.device_id not in registered_ids:
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
        suggested_area = cdev.room_name if cdev else None

        return DeviceInfo(
            identifiers={(DOMAIN, f"cloud_{self._device_id}")},
            name=self.name,
            manufacturer=manufacturer,
            model=model,
            sw_version=sw_version,
            suggested_area=suggested_area,
            configuration_url="https://home.google.com/",
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

        if (
            "action.devices.traits.Oscillation" in traits
            or "isOscillating" in cdev.state
        ):
            features |= FanEntityFeature.OSCILLATE

        if "action.devices.traits.Reverse" in traits or "fanDirection" in cdev.state:
            features |= FanEntityFeature.DIRECTION

        return features

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
        return None

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

        cdev.state["on"] = True
        cdev.state["is_on"] = True
        if percentage is not None:
            cdev.state["currentFanSpeedPercent"] = percentage
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

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        cdev.state["on"] = False
        cdev.state["is_on"] = False
        await self.coordinator.cloud_client.async_execute_command(
            self._device_id,
            "action.devices.commands.OnOff",
            {"on": False},
        )
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set fan speed percentage."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        if percentage == 0:
            await self.async_turn_off()
            return

        cdev.state["on"] = True
        cdev.state["currentFanSpeedPercent"] = percentage
        await self.coordinator.cloud_client.async_execute_command(
            self._device_id,
            "action.devices.commands.SetFanSpeed",
            {"fanSpeedPercent": percentage},
        )
        self.async_write_ha_state()

    async def async_oscillate(self, oscillating: bool) -> None:
        """Set fan oscillation."""
        cdev = self.get_cloud_device()
        if not cdev:
            return

        cdev.state["isOscillating"] = oscillating
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
        await self.coordinator.cloud_client.async_execute_command(
            self._device_id,
            "action.devices.commands.SetFanDirection",
            {"direction": direction},
        )
        self.async_write_ha_state()
