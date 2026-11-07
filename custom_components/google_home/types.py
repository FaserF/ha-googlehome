"""Type definitions for Google Home."""

from __future__ import annotations

from typing import Any, TypedDict

from homeassistant.config_entries import ConfigEntry

GoogleHomeConfigEntry = ConfigEntry


class GoogleHomeAlarmDict(TypedDict):
    """Alarm dictionary representation."""

    alarm_id: str
    fire_time: int
    local_time: str
    local_time_iso: str
    status: str
    label: str | None
    recurrence: str | None


class GoogleHomeTimerDict(TypedDict):
    """Timer dictionary representation."""

    timer_id: str
    fire_time: int | None
    local_time: str | None
    local_time_iso: str | None
    duration: str
    duration_seconds: int
    remaining: str | None
    status: str
    label: str | None


class AlarmsAttributes(TypedDict, total=False):
    """Alarms sensor attributes."""

    next_alarm_status: str
    alarm_volume: float | None
    alarms: list[GoogleHomeAlarmDict]
    booted_at: str | None
    uptime_seconds: float | None
    wifi_ssid: str | None
    wifi_signal_strength_dbm: int | None
    wifi_bssid: str | None
    ip_address: str | None
    mac_address: str | None
    home: str | None


class TimersAttributes(TypedDict, total=False):
    """Timers sensor attributes."""

    next_timer_status: str
    next_timer_remaining: str | None
    timers: list[GoogleHomeTimerDict]


class DeviceAttributes(TypedDict, total=False):
    """Device sensor attributes."""

    device_id: str | None
    device_name: str
    auth_token: str | None
    ip_address: str | None
    available: bool
    hardware: str | None
    firmware_version: str | None
    mac_address: str | None


class AlarmJsonDict(TypedDict):
    """Alarm JSON representation from Google Home API."""

    id: str
    fire_time: int
    status: int
    label: str | None
    recurrence: str | None


class TimerJsonDict(TypedDict):
    """Timer JSON representation from Google Home API."""

    id: str
    fire_time: int | None
    original_duration: int
    status: int
    label: str | None


JsonDict = dict[str, Any]
