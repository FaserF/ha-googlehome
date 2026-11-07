"""Config entry migration routines for Google Home integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    AUTH_METHOD_APP_PASSWORD,
    AUTH_METHOD_TOKEN,
    CONF_ANDROID_ID,
    CONF_AUTH_METHOD,
    CONF_IGNORE_HA_SYNCED_DEVICES,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DEFAULT_IGNORE_HA_SYNCED_DEVICES,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MIN_LOCAL_UPDATE_INTERVAL,
    MODE_LOCAL,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new schema version.

    Handles two distinct cases:
    1. Entries created by leikoilja/ha-google-home (VERSION=1, no auth_method key).
       These are migrated automatically to VERSION=3 with sensible defaults so the
       user never sees a broken entry after replacing the custom_component files.
    2. Our own older VERSION=1 / VERSION=2 entries.
    """
    _LOGGER.debug("Migrating configuration from version %s", config_entry.version)

    # ------------------------------------------------------------------ #
    # Detect and migrate a leikoilja/ha-google-home legacy entry.
    # Fingerprint: VERSION=1 AND no "auth_method" key in entry data.
    # leikoilja stored: username, password, android_id, master_token,
    #                   update_interval (optional, int seconds).
    # ------------------------------------------------------------------ #
    if config_entry.version == 1 and CONF_AUTH_METHOD not in config_entry.data:
        _LOGGER.info(
            "Detected leikoilja/ha-google-home config entry for '%s' — "
            "auto-migrating to FaserF/ha-googlehome schema",
            config_entry.data.get(CONF_USERNAME, "<unknown>"),
        )

        old_data = config_entry.data
        username: str = old_data.get(CONF_USERNAME, "")
        password: str | None = old_data.get(CONF_PASSWORD)
        master_token: str | None = old_data.get(CONF_MASTER_TOKEN)
        android_id: str | None = old_data.get(CONF_ANDROID_ID)

        # leikoilja's update_interval was in seconds (default 180s)
        legacy_update_interval: int = int(
            old_data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        local_update_interval = max(MIN_LOCAL_UPDATE_INTERVAL, legacy_update_interval)

        # Determine best auth_method based on what credentials are present
        auth_method = AUTH_METHOD_TOKEN if master_token else AUTH_METHOD_APP_PASSWORD

        new_data: dict[str, Any] = {
            CONF_AUTH_METHOD: auth_method,
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
            CONF_MASTER_TOKEN: master_token,
            CONF_ANDROID_ID: android_id,
            # leikoilja was purely local → keep Local Only as safe default.
            # Users can switch to Hybrid in Options Flow to gain cloud features.
            CONF_OPERATION_MODE: MODE_LOCAL,
            CONF_IGNORE_HA_SYNCED_DEVICES: DEFAULT_IGNORE_HA_SYNCED_DEVICES,
            CONF_LOCAL_UPDATE_INTERVAL: local_update_interval,
        }
        # Strip None values so optional fields don't clutter the entry
        new_data = {k: v for k, v in new_data.items() if v is not None}

        new_unique_id = username.strip().lower() if username else DOMAIN

        hass.config_entries.async_update_entry(
            config_entry,
            title=f"Google Home ({username})" if username else "Google Home",
            data=new_data,
            unique_id=new_unique_id,
            version=3,
        )
        _LOGGER.info("Successfully auto-migrated leikoilja entry to VERSION=3")
        return True

    # ------------------------------------------------------------------ #
    # Our own VERSION=1 → VERSION=2 migration (bump version, no data change)
    # ------------------------------------------------------------------ #
    if config_entry.version == 1:
        new_data = {**config_entry.data}
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        _LOGGER.info("Successfully migrated Google Home config entry to version 2")

    # ------------------------------------------------------------------ #
    # Our own VERSION=2 → VERSION=3 migration (normalise unique_id)
    # ------------------------------------------------------------------ #
    if config_entry.version == 2:
        v2_username: str | None = config_entry.data.get(CONF_USERNAME)
        new_unique_id = (
            v2_username.strip().lower()
            if v2_username
            else (config_entry.unique_id or DOMAIN)
        )
        hass.config_entries.async_update_entry(
            config_entry,
            unique_id=new_unique_id,
            version=3,
        )
        _LOGGER.info(
            "Successfully migrated Google Home config entry to version 3 (unique_id=%s)",
            new_unique_id,
        )

    return True
