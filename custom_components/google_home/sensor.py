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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ALARM_AND_TIMER_ID_LENGTH,
    DATA_COORDINATOR,
    DOMAIN,
    GOOGLE_HOME_ALARM_DEFAULT_VALUE,
    ICON_ALARMS,
    ICON_BLUETOOTH,
    ICON_TIMERS,
    ICON_TOKEN,
    ICON_WIFI,
    SERVICE_ATTR_ALARM_ID,
    SERVICE_ATTR_SKIP_REFRESH,
    SERVICE_ATTR_TIMER_ID,
    SERVICE_DELETE_ALARM,
    SERVICE_DELETE_TIMER,
    SERVICE_REBOOT,
    SERVICE_REFRESH,
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
        DeviceAttributes,
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
                GoogleHomeDeviceSensor(
                    coordinator=coordinator,
                    device_id=device.device_id,
                    device_name=device.name,
                ),
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
                GoogleHomeWifiSensor(
                    coordinator=coordinator,
                    device_id=device.device_id,
                    device_name=device.name,
                ),
                GoogleHomeBluetoothSensor(
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
        GoogleHomeDeviceSensor.async_reboot_device,
    )

    platform.async_register_entity_service(
        SERVICE_REFRESH,
        {},
        GoogleHomeDeviceSensor.async_refresh_devices,
    )

    platform.async_register_entity_service(
        "set_alarm_volume",
        {
            vol.Required("volume"): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=100)),
        },
        GoogleHomeAlarmsSensor.async_set_alarm_volume,
    )

    return True


class GoogleHomeDeviceSensor(GoogleHomeBaseEntity, SensorEntity):
    """Google Home Device / Connection info sensor."""

    _attr_icon = ICON_TOKEN
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return "device"

    @property
    def native_value(self) -> str | None:
        """Return the device IP address."""
        device = self.get_device()
        return device.ip_address if device else None

    @property
    def extra_state_attributes(self) -> DeviceAttributes:
        """Return device attributes."""
        device = self.get_device()
        return {
            "device_id": device.device_id if device else None,
            "device_name": self.device_name,
            "auth_token": device.auth_token if device else None,
            "ip_address": device.ip_address if device else None,
            "available": device.available if device else False,
        }

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


class GoogleHomeAlarmsSensor(GoogleHomeBaseEntity, SensorEntity):
    """Google Home Alarms sensor."""

    _attr_icon = ICON_ALARMS
    _attr_device_class = SensorDeviceClass.TIMESTAMP

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

    def _get_alarm_volume(self) -> float:
        """Get alarm volume status."""
        device = self.get_device()
        alarm_volume = device.get_alarm_volume() if device else None
        return alarm_volume if alarm_volume else GOOGLE_HOME_ALARM_DEFAULT_VALUE

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


class GoogleHomeTimersSensor(GoogleHomeBaseEntity, SensorEntity):
    """Google Home Timers sensor."""

    _attr_icon = ICON_TIMERS
    _attr_device_class = SensorDeviceClass.TIMESTAMP

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


class GoogleHomeWifiSensor(GoogleHomeBaseEntity, SensorEntity):
    """Google Home Wi-Fi sensor."""

    _attr_icon = ICON_WIFI
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return "wifi"

    @property
    def native_value(self) -> str | None:
        """Return connected Wi-Fi SSID."""
        device = self.get_device()
        return device.get_wifi_ssid() if device else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return Wi-Fi signal level attributes."""
        device = self.get_device()
        rssi = device.get_wifi_rssi() if device else None
        return {
            "signal_level": rssi,
            "ip_address": device.ip_address if device else None,
        }


class GoogleHomeBluetoothSensor(GoogleHomeBaseEntity, SensorEntity):
    """Google Home Bluetooth MAC sensor."""

    _attr_icon = ICON_BLUETOOTH
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return "bluetooth"

    @property
    def native_value(self) -> str | None:
        """Return Bluetooth MAC address."""
        device = self.get_device()
        return device.get_bluetooth_mac() if device else None
