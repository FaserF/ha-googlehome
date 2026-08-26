"""Models for Google Home."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import DATETIME_STR_FORMAT

if TYPE_CHECKING:
    from .types import (
        AlarmJsonDict,
        GoogleHomeAlarmDict,
        GoogleHomeTimerDict,
        TimerJsonDict,
    )


def convert_from_ms_to_s(timestamp: int | float | str) -> int:
    """Convert from milliseconds to seconds."""
    try:
        ts = float(timestamp)
        return round(ts / 1000)
    except (ValueError, TypeError):
        return 0


class GoogleHomeDevice:
    """Local representation of Google Home device."""

    def __init__(
        self,
        device_id: str,
        name: str,
        auth_token: str | None,
        ip_address: str | None = None,
        hardware: str | None = None,
        structure_id: str | None = None,
        structure_name: str | None = None,
    ):
        """Create Google Home device object."""
        self.device_id = device_id
        self.name = name
        self.auth_token = auth_token
        self.ip_address = ip_address
        self.hardware = hardware
        self.structure_id = structure_id
        self.structure_name = structure_name
        self.firmware_version: str | None = None
        self.mac_address: str | None = None
        self.available = True
        self._do_not_disturb = False
        self._alarm_volume: float | None = None
        self._device_volume: float | None = None
        self._night_mode = False
        self._wifi_rssi: int | None = None
        self._wifi_ssid: str | None = None
        self._bluetooth_mac: str | None = None
        self._timers: list[GoogleHomeTimer] = []
        self._alarms: list[GoogleHomeAlarm] = []

    @property
    def manufacturer(self) -> str:
        """Return the device manufacturer (e.g. LG, Lenovo, JBL, Google)."""
        hw = (self.hardware or "").lower()
        nm = self.name.lower()
        if "lg" in hw or "wk7" in hw or "thinq" in hw or "lg " in nm:
            return "LG Electronics"
        if "lenovo" in hw or "cd-" in hw or "lenovo" in nm:
            return "Lenovo"
        if "jbl" in hw or "link" in hw or "jbl" in nm:
            return "JBL"
        if "sony" in hw or "lf-" in hw or "sony" in nm:
            return "Sony"
        if "bose" in hw or "bose" in nm:
            return "Bose"
        if "harman" in hw or "kardon" in hw:
            return "Harman Kardon"
        if "marshall" in hw or "marshall" in nm:
            return "Marshall"
        if "panasonic" in hw or "panasonic" in nm:
            return "Panasonic"
        if "insignia" in hw:
            return "Insignia"
        if "polk" in hw:
            return "Polk Audio"
        if "sonos" in hw or "sonos" in nm:
            return "Sonos"
        if "instar" in hw or "in-" in hw or "instar" in nm or "in-8015" in nm:
            return "INSTAR"
        if "xiaomi" in hw or "xiaomi" in nm or "mi " in nm or "roborock" in hw:
            return "Xiaomi"
        return "Google"

    @property
    def model_name(self) -> str:
        """Return the model name of the Google Home device."""
        if self.hardware and self.hardware.strip():
            return self.hardware.strip()
        return "Google Cast Device"

    def set_system_info(
        self,
        firmware: str | None = None,
        mac: str | None = None,
    ) -> None:
        """Set firmware version and MAC address."""
        if firmware:
            self.firmware_version = firmware
        if mac:
            self.mac_address = mac

    def set_alarms(self, alarms: list[AlarmJsonDict]) -> None:
        """Store alarms as GoogleHomeAlarm objects."""
        new_alarms = []
        for alarm in alarms:
            if not isinstance(alarm, dict) or "id" not in alarm:
                continue
            fire_time = alarm.get("fire_time")
            if fire_time is None:
                continue
            new_alarms.append(
                GoogleHomeAlarm(
                    alarm_id=str(alarm["id"]),
                    fire_time=fire_time,
                    status=alarm.get("status", 1),
                    label=alarm.get("label"),
                    recurrence=alarm.get("recurrence"),
                )
            )
        self._alarms = new_alarms

    def set_timers(self, timers: list[TimerJsonDict]) -> None:
        """Store timers as GoogleHomeTimer objects."""
        new_timers = []
        for timer in timers:
            if not isinstance(timer, dict) or "id" not in timer:
                continue
            raw_dur = timer.get("original_duration") or timer.get("duration", 0)
            duration_int = int(raw_dur) if isinstance(raw_dur, (int, float, str)) else 0
            raw_status = timer.get("status", 1)
            status_int = (
                int(raw_status)
                if isinstance(raw_status, (int, float, str))
                and str(raw_status).isdigit()
                else 1
            )
            new_timers.append(
                GoogleHomeTimer(
                    timer_id=str(timer["id"]),
                    fire_time=timer.get("fire_time"),
                    duration=duration_int,
                    status=status_int,
                    label=timer.get("label"),
                )
            )
        self._timers = new_timers

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

    def get_alarm_volume(self) -> float | None:
        """Return Alarm Volume status."""
        return self._alarm_volume

    def set_device_volume(self, volume: int | float) -> None:
        """Set normal device media/speech volume level."""
        self._device_volume = float(volume)

    def get_device_volume(self) -> float | None:
        """Return normal device media/speech volume level."""
        return self._device_volume

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

    fire_time: int | None
    status: GoogleHomeTimerStatus

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
        if isinstance(status, str):
            try:
                self.status = GoogleHomeTimerStatus[status.upper()]
            except (KeyError, ValueError):
                self.status = GoogleHomeTimerStatus.NONE
        else:
            try:
                self.status = GoogleHomeTimerStatus(int(status))
            except (ValueError, TypeError):
                self.status = GoogleHomeTimerStatus.NONE
        self.label = label

        if fire_time is None:
            self.fire_time = None
            self.date_time: datetime | None = None
            self.local_time = None
            self.local_time_iso = None
        else:
            self.fire_time = convert_from_ms_to_s(fire_time)
            dt_utc = utc_from_timestamp(self.fire_time)
            dt_local = as_local(dt_utc)
            self.date_time = dt_local
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

    fire_time: int
    status: GoogleHomeAlarmStatus

    def __init__(
        self,
        alarm_id: str,
        fire_time: int | float | str,
        status: int | str,
        label: str | None,
        recurrence: str | None,
    ) -> None:
        """Create Google Home Alarm object."""
        self.alarm_id = alarm_id
        self.fire_time = convert_from_ms_to_s(fire_time)
        if isinstance(status, str):
            try:
                self.status = GoogleHomeAlarmStatus[status.upper()]
            except (KeyError, ValueError):
                self.status = GoogleHomeAlarmStatus.NONE
        else:
            try:
                self.status = GoogleHomeAlarmStatus(int(status))
            except (ValueError, TypeError):
                self.status = GoogleHomeAlarmStatus.NONE
        self.label = label
        self.recurrence = recurrence
        dt_utc = utc_from_timestamp(self.fire_time)
        dt_local = as_local(dt_utc)
        self.date_time: datetime = dt_local
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
