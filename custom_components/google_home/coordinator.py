"""DataUpdateCoordinator for Google Home integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, EVENT_ALARM_TRIGGERED, EVENT_TIMER_FINISHED
from .models import GoogleHomeAlarmStatus, GoogleHomeDevice, GoogleHomeTimerStatus

if TYPE_CHECKING:
    from .api import GlocaltokensApiClient

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeDataUpdateCoordinator(DataUpdateCoordinator[list[GoogleHomeDevice]]):
    """Class to manage fetching data from Google Home devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: GlocaltokensApiClient,
        update_interval: int,
    ) -> None:
        """Initialize."""
        self.client = client
        self._previous_active_timers: dict[str, set[str]] = {}
        self._previous_active_alarms: dict[str, set[str]] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> list[GoogleHomeDevice]:
        """Update data via client and fire events for finished timers / triggered alarms."""
        try:
            devices = await self.client.update_google_devices_information()
            self._check_and_fire_events(devices)
            return devices
        except Exception as err:
            raise UpdateFailed(f"Error updating Google Home devices: {err}") from err

    def _check_and_fire_events(self, devices: list[GoogleHomeDevice]) -> None:
        """Check for expired timers and triggered alarms and fire HA bus events."""
        for device in devices:
            device_id = device.device_id

            # Check Timers
            current_active_timers = {
                t.timer_id: t
                for t in device.get_sorted_timers()
                if t.status == GoogleHomeTimerStatus.SET
            }
            prev_timer_ids = self._previous_active_timers.get(device_id, set())

            # Detect timers that disappeared (finished/expired)
            for old_id in prev_timer_ids:
                if old_id not in current_active_timers:
                    self.hass.bus.async_fire(
                        EVENT_TIMER_FINISHED,
                        {
                            "device_id": device_id,
                            "device_name": device.name,
                            "timer_id": old_id,
                        },
                    )

            self._previous_active_timers[device_id] = set(current_active_timers.keys())

            # Check Alarms
            current_active_alarms = {
                a.alarm_id: a
                for a in device.get_sorted_alarms()
                if a.status == GoogleHomeAlarmStatus.SET
            }
            prev_alarm_ids = self._previous_active_alarms.get(device_id, set())

            for old_id in prev_alarm_ids:
                if old_id not in current_active_alarms:
                    self.hass.bus.async_fire(
                        EVENT_ALARM_TRIGGERED,
                        {
                            "device_id": device_id,
                            "device_name": device.name,
                            "alarm_id": old_id,
                        },
                    )

            self._previous_active_alarms[device_id] = set(current_active_alarms.keys())

    def get_device(self, device_id: str) -> GoogleHomeDevice | None:
        """Get device by ID from latest coordinator data."""
        if not self.data:
            return None
        for device in self.data:
            if device.device_id == device_id:
                return device
        return None
