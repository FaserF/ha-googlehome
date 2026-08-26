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
    cloud_coordinator = data.get("cloud_coordinator")
    client = data.get(DATA_CLIENT)
    cloud_client = data.get("cloud_client")

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

    cloud_devices_data = []
    if cloud_coordinator and cloud_coordinator.data:
        for cdev in cloud_coordinator.data:
            cdev_info = {
                "name": cdev.name,
                "device_id": cdev.device_id,
                "device_type": cdev.device_type,
                "hardware_model": cdev.hardware_model,
                "hardware_version": cdev.hardware_version,
                "firmware_version": cdev.firmware_version,
                "mac_address": cdev.mac_address,
                "agent_id": cdev.agent_id,
                "agent_name": cdev.agent_name,
                "traits": cdev.traits,
                "is_ha_synced": cdev.is_home_assistant_synced,
            }
            cloud_devices_data.append(async_redact_data(cdev_info, REDACT_DEVICE))

    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "domain": entry.domain,
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": dict(entry.options),
        },
        "devices": devices_data,
        "cloud_devices": cloud_devices_data,
        "client_initialized": client is not None,
        "cloud_client_initialized": cloud_client is not None,
    }
