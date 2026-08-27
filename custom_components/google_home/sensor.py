"""Sensor platform for Google Home."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator
from .cloud_models import CloudHomeDevice
from .const import (
    ALARM_AND_TIMER_ID_LENGTH,
    CONF_THIRD_PARTY_ENTITY_MODE,
    DATA_CLOUD_COORDINATOR,
    DATA_COORDINATOR,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    MANUFACTURER,
    SERVICE_ATTR_ALARM_ID,
    SERVICE_ATTR_MESSAGE,
    SERVICE_ATTR_SKIP_REFRESH,
    SERVICE_ATTR_TIMER_ID,
    SERVICE_BROADCAST,
    SERVICE_DELETE_ALARM,
    SERVICE_DELETE_TIMER,
    SERVICE_REBOOT,
    SERVICE_REFRESH,
    THIRD_PARTY_MODE_READONLY,
)
from .entity import GoogleHomeBaseEntity
from .models import (
    GoogleHomeAlarm,
    GoogleHomeAlarmStatus,
    GoogleHomeDevice,
    GoogleHomeTimer,
    GoogleHomeTimerStatus,
)

if TYPE_CHECKING:
    from .coordinator import GoogleHomeDataUpdateCoordinator
    from .types import (
        AlarmsAttributes,
        GoogleHomeAlarmDict,
        GoogleHomeTimerDict,
        TimersAttributes,
    )

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the Google Home sensors from a config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator: GoogleHomeDataUpdateCoordinator | None = entry_data.get(
        DATA_COORDINATOR
    )

    entities: list[GoogleHomeBaseEntity] = []
    registered_device_ids: set[str] = set()

    if coordinator is not None:

        def _create_entities_for_device(
            device: GoogleHomeDevice,
        ) -> list[GoogleHomeBaseEntity]:
            registered_device_ids.add(device.device_id)
            return [
                GoogleHomeAlarmsSensor(
                    coordinator=coordinator,
                    device_id=device.device_id,
                    device_name=device.name,
                ),
                GoogleHomeTimersSensor(
                    coordinator=coordinator,
                    device_id=device.device_id,
                    device_name=device.name,
                ),
            ]

        for device in coordinator.data or []:
            entities.extend(_create_entities_for_device(device))

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

    if entities:
        async_add_entities(entities)

    cloud_coordinator: GoogleHomeCloudDataUpdateCoordinator | None = entry_data.get(
        DATA_CLOUD_COORDINATOR
    )
    if cloud_coordinator is not None:
        cloud_registered_ids: set[str] = set()
        third_party_mode = entry.options.get(
            CONF_THIRD_PARTY_ENTITY_MODE,
            entry.data.get(
                CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
            ),
        )

        registered_struct_sensor_ids: set[str] = set()

        def _create_cloud_sensor_entities() -> list[SensorEntity]:
            new_ents: list[SensorEntity] = []
            homes: dict[str, str] = {}
            if hasattr(cloud_coordinator.client, "_get_available_homes_sync"):
                try:
                    homes.update(cloud_coordinator.client._get_available_homes_sync())
                except Exception:
                    pass

            for dev in cloud_coordinator.data or []:
                if dev.structure_id:
                    homes.setdefault(
                        dev.structure_id, dev.structure_name or "Google Home"
                    )
                if dev.is_automation_routine:
                    continue
                if dev.is_control_bridge and dev.device_id not in cloud_registered_ids:
                    cloud_registered_ids.add(dev.device_id)
                    new_ents.append(
                        GoogleHomeCloudBridgeSensor(
                            coordinator=cloud_coordinator,
                            entry_id=entry.entry_id,
                            device_id=dev.device_id,
                        )
                    )
                elif dev.device_id not in cloud_registered_ids:
                    cloud_registered_ids.add(dev.device_id)
                    is_primary = (
                        third_party_mode == THIRD_PARTY_MODE_READONLY
                        and dev.is_third_party
                    )
                    new_ents.append(
                        GoogleHomeCloudStatusSensor(
                            coordinator=cloud_coordinator,
                            device_id=dev.device_id,
                            as_diagnostic=not is_primary,
                        )
                    )
                    # For smart clocks with secondary nightlight trait, also create a dedicated Nightlight status sensor
                    if any(
                        k in (dev.hardware_model or "").lower()
                        or k in (dev.name or "").lower()
                        for k in ("clock", "uhr", "cd-")
                    ) or "action.devices.traits.NightLight" in (dev.traits or []):
                        new_ents.append(
                            GoogleHomeClockNightlightSensor(
                                coordinator=cloud_coordinator,
                                device_id=dev.device_id,
                            )
                        )

            # Structure-level sensors: Home Briefs (Gemini activity summaries) and Face Library (Nest Aware)
            for sid, sname in homes.items():
                if sid not in registered_struct_sensor_ids:
                    registered_struct_sensor_ids.add(sid)
                    new_ents.append(
                        GoogleHomeBriefsSensor(
                            coordinator=cloud_coordinator,
                            entry_id=entry.entry_id,
                            structure_id=sid,
                            structure_name=sname,
                        )
                    )
                    new_ents.append(
                        GoogleHomeFaceLibrarySensor(
                            coordinator=cloud_coordinator,
                            entry_id=entry.entry_id,
                            structure_id=sid,
                            structure_name=sname,
                        )
                    )

            return new_ents

        cloud_sensor_entities = _create_cloud_sensor_entities()
        if cloud_sensor_entities:
            async_add_entities(cloud_sensor_entities)

        @callback
        def _async_add_new_cloud_sensors() -> None:
            new_ents = _create_cloud_sensor_entities()
            if new_ents:
                async_add_entities(new_ents)

        entry.async_on_unload(
            cloud_coordinator.async_add_listener(_async_add_new_cloud_sensors)
        )

    # Register entity services
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_DELETE_ALARM,
        {
            vol.Required(SERVICE_ATTR_ALARM_ID): cv.string,
            vol.Optional(SERVICE_ATTR_SKIP_REFRESH, default=False): cv.boolean,
        },
        GoogleHomeAlarmsSensor.async_delete_alarm,
    )

    platform.async_register_entity_service(
        SERVICE_DELETE_TIMER,
        {
            vol.Required(SERVICE_ATTR_TIMER_ID): cv.string,
            vol.Optional(SERVICE_ATTR_SKIP_REFRESH, default=False): cv.boolean,
        },
        GoogleHomeTimersSensor.async_delete_timer,
    )

    platform.async_register_entity_service(
        SERVICE_REBOOT,
        {},
        GoogleHomeAlarmsSensor.async_reboot_device,
    )

    platform.async_register_entity_service(
        SERVICE_REFRESH,
        {},
        GoogleHomeAlarmsSensor.async_refresh_devices,
    )

    platform.async_register_entity_service(
        "set_alarm_volume",
        {
            vol.Required("volume"): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=100)),
        },
        GoogleHomeAlarmsSensor.async_set_alarm_volume,
    )

    platform.async_register_entity_service(
        SERVICE_BROADCAST,
        {
            vol.Required(SERVICE_ATTR_MESSAGE): cv.string,
        },
        GoogleHomeAlarmsSensor.async_broadcast,
    )

    return True


class GoogleHomeAlarmsSensor(GoogleHomeBaseEntity, SensorEntity):
    """Google Home Alarms sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def icon(self) -> str:
        """Return dynamic icon based on active alarm status."""
        return "mdi:alarm-check" if self.native_value is not None else "mdi:alarm-off"

    async def async_reboot_device(self) -> None:
        """Service call to reboot device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        await self.client.reboot_device(device=device)

    async def async_refresh_devices(self) -> None:
        """Service call to refresh coordinator data."""
        await self.coordinator.async_request_refresh()

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return "alarms"

    @property
    def native_value(self) -> datetime | None:
        """Return next alarm datetime (or None if none set)."""
        device = self.get_device()
        if not device:
            return None
        next_alarm = device.get_next_alarm()
        return (
            next_alarm.date_time
            if next_alarm
            and next_alarm.status
            not in (GoogleHomeAlarmStatus.INACTIVE, GoogleHomeAlarmStatus.MISSED)
            else None
        )

    @property
    def extra_state_attributes(self) -> AlarmsAttributes:
        """Return the state attributes."""
        return {
            "next_alarm_status": self._get_next_alarm_status(),
            "alarm_volume": self._get_alarm_volume(),
            "alarms": self._get_alarms_data(),
        }

    def _get_next_alarm_status(self) -> str:
        """Get next alarm status."""
        device = self.get_device()
        next_alarm = device.get_next_alarm() if device else None
        return (
            next_alarm.status.name.lower()
            if next_alarm
            else GoogleHomeAlarmStatus.NONE.name.lower()
        )

    def _get_alarm_volume(self) -> float | None:
        """Get alarm volume status."""
        device = self.get_device()
        return device.get_alarm_volume() if device else None

    def _get_alarms_data(self) -> list[GoogleHomeAlarmDict]:
        """Get alarms data as list of dictionaries."""
        device = self.get_device()
        alarms: list[GoogleHomeAlarm] = (
            device.get_sorted_alarms() if device is not None else []
        )
        return [alarm.as_dict() for alarm in alarms]

    @staticmethod
    def is_valid_alarm_id(alarm_id: str) -> bool:
        """Check if the alarm id provided is valid."""
        return (
            alarm_id.startswith("alarm/") and len(alarm_id) == ALARM_AND_TIMER_ID_LENGTH
        )

    async def async_delete_alarm(self, call: ServiceCall) -> None:
        """Service call to delete alarm on device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        alarm_id: str = call.data[SERVICE_ATTR_ALARM_ID]
        if not self.is_valid_alarm_id(alarm_id):
            _LOGGER.error("Invalid alarm ID: %s", alarm_id)
            return

        await self.client.delete_alarm_or_timer(device=device, item_to_delete=alarm_id)
        if not call.data.get(SERVICE_ATTR_SKIP_REFRESH, False):
            await self.coordinator.async_request_refresh()

    async def async_set_alarm_volume(self, call: ServiceCall) -> None:
        """Service call to set alarm volume on device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        volume: int = int(call.data["volume"])
        await self.client.update_alarm_volume(device=device, volume=volume)
        self.async_write_ha_state()

    async def async_broadcast(self, call: ServiceCall) -> None:
        """Service call to broadcast announcement on Google Home device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        message: str = str(call.data[SERVICE_ATTR_MESSAGE])
        await self.client.broadcast_message(device=device, message=message)


class GoogleHomeTimersSensor(GoogleHomeBaseEntity, SensorEntity):
    """Google Home Timers sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def icon(self) -> str:
        """Return dynamic icon based on active timer status."""
        return (
            "mdi:timer-outline"
            if self.native_value is not None
            else "mdi:timer-off-outline"
        )

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return "timers"

    @property
    def native_value(self) -> datetime | None:
        """Return next timer datetime (or None if none set)."""
        device = self.get_device()
        if not device:
            return None
        next_timer = device.get_next_timer()
        if (
            next_timer
            and next_timer.status != GoogleHomeTimerStatus.NONE
            and next_timer.date_time
        ):
            return next_timer.date_time
        return None

    @property
    def extra_state_attributes(self) -> TimersAttributes:
        """Return the state attributes."""
        return {
            "next_timer_status": self._get_next_timer_status(),
            "timers": self._get_timers_data(),
        }

    def _get_next_timer_status(self) -> str:
        """Get next timer status."""
        device = self.get_device()
        next_timer = device.get_next_timer() if device else None
        return (
            next_timer.status.name.lower()
            if next_timer
            else GoogleHomeTimerStatus.NONE.name.lower()
        )

    def _get_timers_data(self) -> list[GoogleHomeTimerDict]:
        """Get timers data as list of dictionaries."""
        device = self.get_device()
        timers: list[GoogleHomeTimer] = (
            device.get_sorted_timers() if device is not None else []
        )
        return [timer.as_dict() for timer in timers]

    @staticmethod
    def is_valid_timer_id(timer_id: str) -> bool:
        """Check if the timer id provided is valid."""
        return (
            timer_id.startswith("timer/") and len(timer_id) == ALARM_AND_TIMER_ID_LENGTH
        )

    async def async_delete_timer(self, call: ServiceCall) -> None:
        """Service call to delete timer on device."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        timer_id: str = call.data[SERVICE_ATTR_TIMER_ID]
        if not self.is_valid_timer_id(timer_id):
            _LOGGER.error("Invalid timer ID: %s", timer_id)
            return

        await self.client.delete_alarm_or_timer(device=device, item_to_delete=timer_id)
        if not call.data.get(SERVICE_ATTR_SKIP_REFRESH, False):
            await self.coordinator.async_request_refresh()


class GoogleHomeCloudBridgeSensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Home Cloud Bridge / Hub diagnostic sensor."""

    _attr_icon = "mdi:bridge"
    # Bridges are diagnostic only and disabled by default to reduce clutter
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        entry_id: str,
        device_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_bridge_status"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return f"{device.name} Status" if device else "Bridge Status"

    @property
    def native_value(self) -> str:
        """Return online status of bridge."""
        device = self.get_device()
        if not device:
            return "unavailable"
        return "online" if device.online else "offline"

    @property
    def available(self) -> bool:
        """Return availability."""
        device = self.get_device()
        return device is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return bridge diagnostic attributes."""
        device = self.get_device()
        if not device:
            return {}
        return {
            "bridge_name": device.name,
            "device_id": device.device_id,
            "device_type": device.device_type,
            "traits": device.traits,
            "agent_id": device.agent_id,
            "agent_name": device.agent_name,
            "hardware_model": device.hardware_model,
            "structure": device.structure_name,
            "room": device.room_name,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info grouping bridge sensor under its Google Home household main device."""
        device = self.get_device()
        struct_id = (
            device.structure_id if device and device.structure_id else "default_home"
        )
        struct_name = (
            device.structure_name if device and device.structure_name else "Google Home"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_structure_{struct_id}")},
            name=f"Google Home ({struct_name})",
            manufacturer=MANUFACTURER,
            model="Google Home Household & Structure",
            configuration_url="https://home.google.com/",
        )


class GoogleHomeCloudStatusSensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Home Cloud status sensor.

    Always registered for all cloud devices (third-party and Google-native).
    In readonly mode for third-party devices: primary entity (no category).
    In control mode or for Google-native devices: supplemental diagnostic entity.
    """

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
        as_diagnostic: bool = False,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_status"
        if as_diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def name(self) -> str:
        """Return name."""
        device = self.get_device()
        return f"{device.name} Status" if device else "Google Device Status"

    @property
    def native_value(self) -> str:
        """Return human-readable device state. Never returns 'online'."""
        device = self.get_device()
        if not device:
            return "unavailable"
        return device.get_human_status()

    @property
    def icon(self) -> str:
        """Return dynamic icon based on device type and live state."""
        device = self.get_device()
        if not device:
            return "mdi:cloud-outline"
        val = str(self.native_value).lower()
        is_active = (
            val.startswith("on")
            or val
            in (
                "open",
                "playing",
                "cleaning",
                "running",
                "unlocked",
                "heat",
                "cool",
                "auto",
            )
            or "open (" in val
        )
        dtype = device.device_type.upper()

        if "LIGHT" in dtype:
            return "mdi:lightbulb-on" if is_active else "mdi:lightbulb-outline"
        if "SWITCH" in dtype or "OUTLET" in dtype or "PLUG" in dtype:
            return "mdi:power-socket-eu" if is_active else "mdi:power-socket-eu"
        if "FAN" in dtype or "AIRPURIFIER" in dtype:
            return "mdi:fan" if is_active else "mdi:fan-off"
        if "VACUUM" in dtype or "MOWER" in dtype:
            return (
                "mdi:robot-vacuum" if val == "cleaning" else "mdi:robot-vacuum-variant"
            )
        if "SHUTTER" in dtype or "BLINDS" in dtype or "CURTAIN" in dtype:
            return "mdi:window-shutter-open" if is_active else "mdi:window-shutter"
        if "LOCK" in dtype:
            return "mdi:lock-open-variant" if val == "unlocked" else "mdi:lock"
        if "TV" in dtype or "SETTOP" in dtype:
            return "mdi:television" if is_active else "mdi:television-off"
        if "SPEAKER" in dtype or "SOUNDBAR" in dtype:
            return "mdi:speaker-play" if val == "playing" else "mdi:speaker"
        if "THERMOSTAT" in dtype or "AC_UNIT" in dtype or "HEATER" in dtype:
            return "mdi:thermostat"
        if "CAMERA" in dtype or "DOORBELL" in dtype:
            return "mdi:camera"
        if "VALVE" in dtype or "SPRINKLER" in dtype or "FAUCET" in dtype:
            return "mdi:pipe-valve"
        if "GARAGE" in dtype:
            return "mdi:garage-open" if is_active else "mdi:garage"
        if "FRYER" in dtype or "COOKER" in dtype:
            return "mdi:pot-steam" if is_active else "mdi:pot"

        return "mdi:cloud-check" if is_active else "mdi:cloud-outline"

    @property
    def available(self) -> bool:
        """Return availability."""
        device = self.get_device()
        return device is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all state, network and diagnostic attributes."""
        device = self.get_device()
        if not device:
            return {}

        # Look up local speaker counterpart for network and Wi-Fi diagnostics if present
        local_ip: str | None = None
        wifi_ssid: str | None = None
        wifi_rssi: int | None = None
        bt_mac: str | None = None
        activity: str | None = None

        config_entry = getattr(self.coordinator, "config_entry", None)
        entry_id = getattr(config_entry, "entry_id", None) if config_entry else None
        if entry_id and entry_id in self.hass.data.get(DOMAIN, {}):
            local_coord = self.hass.data[DOMAIN][entry_id].get("coordinator")
            if local_coord:
                for ldev in local_coord.data or []:
                    if ldev.name.lower() == device.name.lower() or (
                        ldev.device_id and ldev.device_id == device.device_id
                    ):
                        local_ip = ldev.ip_address
                        wifi_ssid = ldev.get_wifi_ssid()
                        wifi_rssi = ldev.get_wifi_rssi()
                        bt_mac = ldev.get_bluetooth_mac()
                        activity = "idle" if ldev.available else "offline"
                        break

        attrs: dict[str, Any] = {
            "online": device.online,
            "device_type": device.device_type,
            "traits": device.traits,
            "agent_id": device.agent_id,
            "agent_name": device.agent_name,
            "hardware_model": device.hardware_model,
            "hardware_version": device.hardware_version,
            "firmware_version": device.firmware_version,
            "mac_address": device.mac_address,
            "bluetooth_mac": bt_mac,
            "device_ip": local_ip,
            "wifi_network": wifi_ssid,
            "wifi_signal_level": wifi_rssi,
            "activity": activity,
            "brightness": device.state.get("brightness"),
            "open_percent": device.state.get("openPercent"),
            "is_locked": device.state.get("isLocked"),
            "structure": device.structure_name,
            "room": device.room_name,
            "state_data": device.state,
            "attributes_data": device.attributes,
        }
        return {
            k: v
            for k, v in attrs.items()
            if v is not None and v != "" and v != [] and v != {}
        }

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
            name=device.name if device else "Device",
            manufacturer=device.manufacturer if device else MANUFACTURER,
            model=device.model_name if device else "Cloud Device",
            sw_version=device.firmware_version if device else None,
            hw_version=device.hardware_version if device else None,
            suggested_area=device.room_name if device else None,
            connections=connections,
            configuration_url="https://home.google.com/",
        )


class GoogleHomeClockNightlightSensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Home Smart Clock Nightlight Status sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "nightlight_status"

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_cloud_nightlight_status"

    def get_device(self) -> CloudHomeDevice | None:
        """Get device from coordinator."""
        return self.coordinator.get_device(self.device_id)

    @property
    def native_value(self) -> str:
        """Return nightlight state (on (X%), on, off)."""
        device = self.get_device()
        if not device or not device.online:
            return "unavailable" if not device else "offline"
        state = device.state
        is_on = bool(state.get("nightlight_on", False))
        if not is_on:
            return "off"
        if "brightness" in state:
            bri = state["brightness"]
            return f"on ({bri}%)" if bri is not None else "on"
        return "on"

    @property
    def icon(self) -> str:
        """Return dynamic MDI lightbulb icon."""
        val = str(self.native_value).lower()
        is_active = val.startswith("on")
        return "mdi:lightbulb-on" if is_active else "mdi:lightbulb-outline"

    @property
    def available(self) -> bool:
        """Return availability."""
        device = self.get_device()
        return device is not None and device.online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return nightlight attributes."""
        device = self.get_device()
        if not device:
            return {}
        attrs: dict[str, Any] = {
            "brightness": device.state.get("brightness"),
            "traits": device.traits,
            "state_data": device.state,
        }
        return {
            k: v
            for k, v in attrs.items()
            if v is not None and v != "" and v != [] and v != {}
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info."""
        device = self.get_device()
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device.name if device else "Device",
            manufacturer=device.manufacturer if device else MANUFACTURER,
            model=device.model_name if device else "Cloud Device",
        )


class GoogleHomeBriefsSensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Home Gemini / Home Agent daily activity brief summary sensor."""

    _attr_icon = "mdi:text-box-search-outline"
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        entry_id: str,
        structure_id: str,
        structure_name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.structure_id = structure_id
        self.structure_name = structure_name
        self._attr_unique_id = f"google_home_briefs_{structure_id}"

    @property
    def name(self) -> str:
        """Return name."""
        return f"{self.structure_name} Home Briefs"

    def _extract_briefs_data(self) -> dict[str, Any]:
        """Extract HomeBriefsTrait and Gemini info from raw HomeGraph payload."""
        result: dict[str, Any] = {"status": "available", "briefs": []}
        try:
            auth_client = getattr(self.coordinator.client, "_auth_client", None)
            if auth_client and getattr(auth_client, "homegraph", None):
                raw = auth_client.homegraph.SerializeToString()
                import re

                # Extract strings around HomeBriefsTrait
                matches = re.findall(
                    rb"HomeBriefsTrait[^\xaa]*\x1a[\x01-\x40]([^\x00-\x1f]+)", raw
                )
                brief_texts = [
                    m.decode("utf-8", errors="ignore")
                    for m in matches
                    if len(m) > 3 and b"trait" not in m.lower()
                ]
                if brief_texts:
                    result["briefs"] = brief_texts
        except Exception:
            pass
        return result

    @property
    def native_value(self) -> str:
        """Return brief status."""
        data = self._extract_briefs_data()
        briefs = data.get("briefs", [])
        return str(briefs[0]) if briefs else "No recent summaries"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full briefs metadata."""
        data = self._extract_briefs_data()
        return {
            "structure_id": self.structure_id,
            "structure_name": self.structure_name,
            "all_briefs": data.get("briefs", []),
            "total_briefs": len(data.get("briefs", [])),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return household device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_structure_{self.structure_id}")},
            name=f"Google Home ({self.structure_name})",
            manufacturer=MANUFACTURER,
            model="Google Home Household & Structure",
            configuration_url="https://home.google.com/",
        )


class GoogleHomeFaceLibrarySensor(
    CoordinatorEntity[GoogleHomeCloudDataUpdateCoordinator], SensorEntity
):
    """Google Nest Aware Familiar Faces Library sensor."""

    _attr_icon = "mdi:account-box-multiple-outline"
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: GoogleHomeCloudDataUpdateCoordinator,
        entry_id: str,
        structure_id: str,
        structure_name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.structure_id = structure_id
        self.structure_name = structure_name
        self._attr_unique_id = f"google_home_face_library_{structure_id}"

    @property
    def name(self) -> str:
        """Return name."""
        return f"{self.structure_name} Familiar Faces"

    def _extract_face_library(self) -> list[str]:
        """Extract FaceLibraryTrait names from raw HomeGraph payload."""
        faces = []
        try:
            auth_client = getattr(self.coordinator.client, "_auth_client", None)
            if auth_client and getattr(auth_client, "homegraph", None):
                raw = auth_client.homegraph.SerializeToString()
                import re

                matches = re.findall(
                    rb"FaceLibraryTrait[^\xaa]*\x1a[\x01-\x30]([^\x00-\x1f]+)", raw
                )
                faces = [
                    m.decode("utf-8", errors="ignore")
                    for m in matches
                    if len(m) > 1 and b"trait" not in m.lower()
                ]
        except Exception:
            pass
        return faces

    @property
    def native_value(self) -> int:
        """Return number of recognized familiar faces."""
        return len(self._extract_face_library())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return recognized familiar face names."""
        faces = self._extract_face_library()
        return {
            "structure_id": self.structure_id,
            "structure_name": self.structure_name,
            "familiar_faces": faces,
            "count": len(faces),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return household device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}_structure_{self.structure_id}")},
            name=f"Google Home ({self.structure_name})",
            manufacturer=MANUFACTURER,
            model="Google Home Household & Structure",
            configuration_url="https://home.google.com/",
        )
