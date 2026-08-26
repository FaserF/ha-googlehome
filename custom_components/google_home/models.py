"""Models for Google Home."""

from __future__ import annotations

import sys
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import DATETIME_STR_FORMAT, GOOGLE_HOME_ALARM_DEFAULT_VALUE

if TYPE_CHECKING:
    from .types import (
        AlarmJsonDict,
        GoogleHomeAlarmDict,
        GoogleHomeTimerDict,
        TimerJsonDict,
    )


def convert_from_ms_to_s(timestamp: int) -> int:
    """Convert from milliseconds to seconds."""
    return round(timestamp / 1000)


class GoogleHomeDevice:
    """Local representation of Google Home device."""

    def __init__(
        self,
        device_id: str,
        name: str,
        auth_token: str | None,
        ip_address: str | None = None,
        hardware: str | None = None,
    ):
        """Create Google Home device object."""
        self.device_id = device_id
        self.name = name
        self.auth_token = auth_token
        self.ip_address = ip_address
        self.hardware = hardware
        self.available = True
        self._do_not_disturb = False
        self._alarm_volume = GOOGLE_HOME_ALARM_DEFAULT_VALUE
        self._night_mode = False
        self._wifi_rssi: int | None = None
        self._wifi_ssid: str | None = None
        self._bluetooth_mac: str | None = None
        self._timers: list[GoogleHomeTimer] = []
        self._alarms: list[GoogleHomeAlarm] = []

    def set_alarms(self, alarms: list[AlarmJsonDict]) -> None:
        """Store alarms as GoogleHomeAlarm objects."""
        self._alarms = [
            GoogleHomeAlarm(
                alarm_id=alarm["id"],
                fire_time=alarm["fire_time"],
                status=alarm["status"],
                label=alarm.get("label"),
                recurrence=alarm.get("recurrence"),
            )
            for alarm in alarms
        ]

    def set_timers(self, timers: list[TimerJsonDict]) -> None:
        """Store timers as GoogleHomeTimer objects."""
        self._timers = [
            GoogleHomeTimer(
                timer_id=timer["id"],
                fire_time=timer.get("fire_time"),
                duration=timer["original_duration"],
                status=timer["status"],
                label=timer.get("label"),
            )
            for timer in timers
        ]

    def get_sorted_alarms(self) -> list[GoogleHomeAlarm]:
        """Return alarms in a sorted order."""
        return sorted(
            self._alarms,
            key=lambda k: (
                k.fire_time
                if k.status
                not in (GoogleHomeAlarmStatus.INACTIVE, GoogleHomeAlarmStatus.MISSED)
                else k.fire_time + sys.maxsize
            ),
        )

    def get_next_alarm(self) -> GoogleHomeAlarm | None:
        """Return next alarm."""
        alarms = self.get_sorted_alarms()
        return alarms[0] if alarms else None

    def get_sorted_timers(self) -> list[GoogleHomeTimer]:
        """Return timers in a sorted order."""
        return sorted(
            self._timers,
            key=lambda k: k.fire_time if k.fire_time is not None else sys.maxsize,
        )

    def get_next_timer(self) -> GoogleHomeTimer | None:
        """Return next timer."""
        timers = self.get_sorted_timers()
        return timers[0] if timers else None

    def set_do_not_disturb(self, status: bool) -> None:
        """Set Do Not Disturb status."""
        self._do_not_disturb = status

    def get_do_not_disturb(self) -> bool:
        """Return Do Not Disturb status."""
        return self._do_not_disturb

    def set_alarm_volume(self, volume: int | float) -> None:
        """Set Alarm Volume status."""
        self._alarm_volume = float(volume)

    def get_alarm_volume(self) -> float:
        """Return Alarm Volume status."""
        return self._alarm_volume

    def set_night_mode(self, status: bool) -> None:
        """Set Night Mode status."""
        self._night_mode = status

    def get_night_mode(self) -> bool:
        """Return Night Mode status."""
        return self._night_mode

    def set_wifi_info(self, ssid: str | None, rssi: int | None) -> None:
        """Set Wi-Fi information."""
        self._wifi_ssid = ssid
        self._wifi_rssi = rssi

    def get_wifi_ssid(self) -> str | None:
        """Return Wi-Fi SSID."""
        return self._wifi_ssid

    def get_wifi_rssi(self) -> int | None:
        """Return Wi-Fi RSSI."""
        return self._wifi_rssi

    def set_bluetooth_mac(self, mac: str | None) -> None:
        """Set Bluetooth MAC address."""
        self._bluetooth_mac = mac

    def get_bluetooth_mac(self) -> str | None:
        """Return Bluetooth MAC address."""
        return self._bluetooth_mac


class GoogleHomeTimer:
    """Local representation of Google Home timer."""

    def __init__(
        self,
        timer_id: str,
        fire_time: int | None,
        duration: int,
        status: int,
        label: str | None,
    ) -> None:
        """Create Google Home Timer object."""
        self.timer_id = timer_id
        duration_seconds = convert_from_ms_to_s(duration)
        self.duration_seconds = duration_seconds
        self.duration = str(timedelta(seconds=duration_seconds))
        try:
            self.status = GoogleHomeTimerStatus(status)
        except ValueError:
            self.status = GoogleHomeTimerStatus.NONE
        self.label = label

        if fire_time is None:
            self.fire_time = None
            self.local_time = None
            self.local_time_iso = None
        else:
            self.fire_time = convert_from_ms_to_s(fire_time)
            dt_utc = utc_from_timestamp(self.fire_time)
            dt_local = as_local(dt_utc)
            self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
            self.local_time_iso = dt_local.isoformat()

    def as_dict(self) -> GoogleHomeTimerDict:
        """Return typed dict representation."""
        return {
            "timer_id": self.timer_id,
            "fire_time": self.fire_time,
            "local_time": self.local_time,
            "local_time_iso": self.local_time_iso,
            "duration": self.duration,
            "duration_seconds": self.duration_seconds,
            "status": self.status.name.lower(),
            "label": self.label,
        }


class GoogleHomeAlarm:
    """Local representation of Google Home alarm."""

    def __init__(
        self,
        alarm_id: str,
        fire_time: int,
        status: int,
        label: str | None,
        recurrence: str | None,
    ) -> None:
        """Create Google Home Alarm object."""
        self.alarm_id = alarm_id
        self.recurrence = recurrence
        self.fire_time = convert_from_ms_to_s(fire_time)
        try:
            self.status = GoogleHomeAlarmStatus(status)
        except ValueError:
            self.status = GoogleHomeAlarmStatus.NONE
        self.label = label

        dt_utc = utc_from_timestamp(self.fire_time)
        dt_local = as_local(dt_utc)
        self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
        self.local_time_iso = dt_local.isoformat()

    def as_dict(self) -> GoogleHomeAlarmDict:
        """Return typed dict representation."""
        return {
            "alarm_id": self.alarm_id,
            "fire_time": self.fire_time,
            "local_time": self.local_time,
            "local_time_iso": self.local_time_iso,
            "status": self.status.name.lower(),
            "label": self.label,
            "recurrence": self.recurrence,
        }


class GoogleHomeAlarmStatus(Enum):
    """Definition of Google Home alarm status."""

    NONE = 0
    SET = 1
    RINGING = 2
    SNOOZED = 3
    INACTIVE = 4
    MISSED = 5


class GoogleHomeTimerStatus(Enum):
    """Definition of Google Home timer status."""

    NONE = 0
    SET = 1
    PAUSED = 2
    RINGING = 3
