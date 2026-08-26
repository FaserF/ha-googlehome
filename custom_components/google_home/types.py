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
    status: str
    label: str | None


class AlarmsAttributes(TypedDict):
    """Alarms sensor attributes."""

    next_alarm_status: str
    alarm_volume: float
    alarms: list[GoogleHomeAlarmDict]


class TimersAttributes(TypedDict):
    """Timers sensor attributes."""

    next_timer_status: str
    timers: list[GoogleHomeTimerDict]


class DeviceAttributes(TypedDict):
    """Device sensor attributes."""

    device_id: str | None
    device_name: str
    auth_token: str | None
    ip_address: str | None
    available: bool


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
