"""Climate platform for Google Home & Nest Cloud devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
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
    get_structure_url,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Google Home climate entities."""
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

    def _create_entities() -> list[GoogleHomeCloudClimate]:
        new_ents = []
        for dev in coordinator.data or []:
            if (
                dev.is_climate
                and dev.device_id not in registered_ids
                and (
                    not dev.is_third_party
                    or third_party_mode != THIRD_PARTY_MODE_READONLY
                )
            ):
                registered_ids.add(dev.device_id)
                new_ents.append(
                    GoogleHomeCloudClimate(
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


class GoogleHomeCloudClimate(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], ClimateEntity
):
    """Google Home Cloud Climate entity."""

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize climate entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_climate"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.HEAT_COOL,
        ]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return device.name if device else "Google Thermostat"

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature."""
        device = self.get_device()
        if not device:
            return None
        return float(device.state.get("thermostatTemperatureAmbient", 20.0))

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        device = self.get_device()
        if not device:
            return None
        return float(device.state.get("thermostatTemperatureSetpoint", 21.0))

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        device = self.get_device()
        if not device:
            return HVACMode.OFF
        mode_str = str(device.state.get("thermostatMode", "heat")).lower()
        if mode_str == "cool":
            return HVACMode.COOL
        if mode_str in ("heatcool", "auto"):
            return HVACMode.HEAT_COOL
        if mode_str == "off":
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def available(self) -> bool:
        """Return available status."""
        device = self.get_device()
        return device.online if device else False

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
            configuration_url=get_structure_url(
                device.structure_id if device else None, "devices"
            ),
        )

    async def _async_send_assistant_command(self, command: str) -> None:
        """Forward command via Google Assistant SDK if installed and available."""
        if self.hass.services.has_service("google_assistant_sdk", "send_text_command"):
            try:
                _LOGGER.debug("Sending Assistant SDK climate command: %s", command)
                await self.hass.services.async_call(
                    "google_assistant_sdk",
                    "send_text_command",
                    {"command": command},
                    blocking=False,
                )
            except Exception as ex:
                _LOGGER.warning("Error invoking google_assistant_sdk: %s", ex)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get("temperature")
        if temp is None:
            return

        device = self.get_device()
        if device:
            device.state["thermostatTemperatureSetpoint"] = temp

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
            await self._async_send_assistant_command(
                format_command(
                    self.hass, "set_temperature", device.name, temperature=temp
                )
            )
        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD and device:
            await self.coordinator.client.async_execute_command(
                device_id=self.device_id,
                command="action.devices.commands.ThermostatTemperatureSetpoint",
                params={"thermostatTemperatureSetpoint": temp},
            )
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        mode_str = str(hvac_mode).split(".")[-1]
        device = self.get_device()
        if device:
            device.state["thermostatMode"] = mode_str

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
            await self._async_send_assistant_command(
                format_command(self.hass, "set_hvac_mode", device.name, mode=mode_str)
            )

        elif third_party_mode == THIRD_PARTY_MODE_DIRECT_CLOUD and device:
            await self.coordinator.client.async_execute_command(
                device_id=self.device_id,
                command="action.devices.commands.ThermostatSetMode",
                params={"thermostatMode": mode_str},
            )
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()
