"""Diagnostics support for Google Home integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ANDROID_ID,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
)

REDACT_CONFIG = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_MASTER_TOKEN,
    CONF_ANDROID_ID,
}

REDACT_DEVICE = {
    "auth_token",
    "ip_address",
    "device_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = data.get(DATA_COORDINATOR)
    client = data.get(DATA_CLIENT)

    devices_data = []
    if coordinator and coordinator.data:
        for device in coordinator.data:
            dev_info = {
                "name": device.name,
                "hardware": device.hardware,
                "available": device.available,
                "do_not_disturb": device.get_do_not_disturb(),
                "alarm_volume": device.get_alarm_volume(),
                "alarms_count": len(device.get_sorted_alarms()),
                "timers_count": len(device.get_sorted_timers()),
                "auth_token": device.auth_token,
                "ip_address": device.ip_address,
                "device_id": device.device_id,
            }
            devices_data.append(async_redact_data(dev_info, REDACT_DEVICE))

    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "domain": entry.domain,
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": dict(entry.options),
        },
        "devices": devices_data,
        "client_initialized": client is not None,
    }
