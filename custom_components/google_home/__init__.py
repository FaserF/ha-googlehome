"""The Google Home component."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GlocaltokensApiClient
from .const import (
    CONF_ANDROID_ID,
    CONF_IGNORE_HA_SYNCED_DEVICES,
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_CLOUD_CLIENT,
    DATA_CLOUD_COORDINATOR,
    DATA_COORDINATOR,
    DEFAULT_IGNORE_HA_SYNCED_DEVICES,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MODE_CLOUD,
    MODE_HYBRID,
    MODE_LOCAL,
    PLATFORMS,
)
from .coordinator import GoogleHomeDataUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Google Home from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    username = cast("str | None", entry.data.get(CONF_USERNAME))
    password = cast("str | None", entry.data.get(CONF_PASSWORD))
    master_token = cast("str | None", entry.data.get(CONF_MASTER_TOKEN))
    android_id = cast("str | None", entry.data.get(CONF_ANDROID_ID))

    mode = entry.options.get(
        CONF_OPERATION_MODE,
        entry.data.get(CONF_OPERATION_MODE, MODE_HYBRID),
    )
    ignore_ha_synced = entry.options.get(
        CONF_IGNORE_HA_SYNCED_DEVICES,
        entry.data.get(CONF_IGNORE_HA_SYNCED_DEVICES, DEFAULT_IGNORE_HA_SYNCED_DEVICES),
    )

    update_interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    session = async_get_clientsession(hass)

    entry_data: dict[str, Any] = {}

    # 1. Setup Local Subsystem
    if mode in (MODE_HYBRID, MODE_LOCAL):
        zeroconf_instance = await zeroconf.async_get_instance(hass)
        client = GlocaltokensApiClient(
            hass=hass,
            session=session,
            username=username,
            password=password,
            master_token=master_token,
            android_id=android_id,
            zeroconf_instance=zeroconf_instance,
        )
        coordinator = GoogleHomeDataUpdateCoordinator(
            hass=hass,
            client=client,
            update_interval=update_interval,
        )
        try:
            await coordinator.async_config_entry_first_refresh()
        except Exception as err:
            _LOGGER.warning("Initial local refresh warning: %s", err)

        entry_data[DATA_CLIENT] = client
        entry_data[DATA_COORDINATOR] = coordinator

    # 2. Setup Cloud Subsystem
    if mode in (MODE_HYBRID, MODE_CLOUD) and master_token:
        from .cloud_api import GoogleHomeCloudClient
        from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator

        cloud_client = GoogleHomeCloudClient(
            hass=hass,
            master_token=master_token,
            ignore_ha_synced=ignore_ha_synced,
        )
        cloud_coordinator = GoogleHomeCloudDataUpdateCoordinator(
            hass=hass,
            client=cloud_client,
            update_interval=update_interval,
        )
        try:
            await cloud_coordinator.async_config_entry_first_refresh()
        except Exception as err:
            _LOGGER.warning("Initial cloud refresh warning: %s", err)

        entry_data[DATA_CLOUD_CLIENT] = cloud_client
        entry_data[DATA_CLOUD_COORDINATOR] = cloud_coordinator

    hass.data[DOMAIN][entry.entry_id] = entry_data

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new schema version."""
    _LOGGER.debug("Migrating configuration from version %s", config_entry.version)

    if config_entry.version == 1:
        # Version 1 was the legacy integration setup.
        # Migrate schema safely to version 2
        new_data = {**config_entry.data}
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        _LOGGER.info("Successfully migrated Google Home config entry to version 2")

    return True
