"""The Google Home component."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GlocaltokensApiClient
from .const import (
    CONF_ANDROID_ID,
    CONF_CLOUD_UPDATE_INTERVAL,
    CONF_IGNORE_HA_SYNCED_DEVICES,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    CONF_PASSWORD,
    CONF_SELECTED_HOMES,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_CLOUD_CLIENT,
    DATA_CLOUD_COORDINATOR,
    DATA_COORDINATOR,
    DEFAULT_CLOUD_UPDATE_INTERVAL,
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
    master_token = cast(
        "str | None",
        entry.options.get(CONF_MASTER_TOKEN, entry.data.get(CONF_MASTER_TOKEN)),
    )
    android_id = cast("str | None", entry.data.get(CONF_ANDROID_ID))

    mode = entry.options.get(
        CONF_OPERATION_MODE,
        entry.data.get(CONF_OPERATION_MODE, MODE_HYBRID),
    )
    ignore_ha_synced = entry.options.get(
        CONF_IGNORE_HA_SYNCED_DEVICES,
        entry.data.get(CONF_IGNORE_HA_SYNCED_DEVICES, DEFAULT_IGNORE_HA_SYNCED_DEVICES),
    )
    selected_homes = entry.options.get(
        CONF_SELECTED_HOMES,
        entry.data.get(CONF_SELECTED_HOMES),
    )
    # Retrieve polling intervals: local (default 60s, min 60s), cloud (default 300s, min 60s)

    legacy_interval = entry.options.get(
        CONF_UPDATE_INTERVAL,
        entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
    )
    local_update_interval = entry.options.get(
        CONF_LOCAL_UPDATE_INTERVAL,
        entry.data.get(CONF_LOCAL_UPDATE_INTERVAL, max(60, legacy_interval)),
    )
    # Enforce minimum 60s for local polling
    local_update_interval = max(60, int(local_update_interval))

    cloud_update_interval = entry.options.get(
        CONF_CLOUD_UPDATE_INTERVAL,
        entry.data.get(CONF_CLOUD_UPDATE_INTERVAL, DEFAULT_CLOUD_UPDATE_INTERVAL),
    )
    # Enforce minimum 60s for cloud polling
    cloud_update_interval = max(60, int(cloud_update_interval))

    session = async_get_clientsession(hass)

    entry_data: dict[str, Any] = {}
    hass.data[DOMAIN][entry.entry_id] = entry_data

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
            selected_homes=selected_homes,
        )
        coordinator = GoogleHomeDataUpdateCoordinator(
            hass=hass,
            client=client,
            update_interval=local_update_interval,
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
            username=username,
            android_id=android_id,
            ignore_ha_synced=ignore_ha_synced,
            selected_homes=selected_homes,
        )
        cloud_coordinator = GoogleHomeCloudDataUpdateCoordinator(
            hass=hass,
            client=cloud_client,
            update_interval=cloud_update_interval,
        )
        try:
            await cloud_coordinator.async_config_entry_first_refresh()
        except Exception as err:
            _LOGGER.warning("Initial cloud refresh warning: %s", err)

        entry_data[DATA_CLOUD_CLIENT] = cloud_client
        entry_data[DATA_CLOUD_COORDINATOR] = cloud_coordinator

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Clean up stale devices and entities from Device and Entity Registries
    await _async_cleanup_stale_devices_and_entities(hass, entry)

    return True


async def _async_cleanup_stale_devices_and_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove devices and entities from registry that are no longer part of active coordinators."""
    from homeassistant.helpers import device_registry as dr

    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    local_coordinator = data.get(DATA_COORDINATOR)
    cloud_coordinator = data.get(DATA_CLOUD_COORDINATOR)

    active_device_ids: set[str] = set()

    if local_coordinator and local_coordinator.data:
        for dev in local_coordinator.data:
            active_device_ids.add(dev.device_id)

    if cloud_coordinator and cloud_coordinator.data:
        for cdev in cloud_coordinator.data:
            active_device_ids.add(cdev.device_id)
            if cdev.structure_id:
                active_device_ids.add(f"{entry.entry_id}_structure_{cdev.structure_id}")
                active_device_ids.add(f"structure_{cdev.structure_id}")
        active_device_ids.add(f"{entry.entry_id}_hub")
        active_device_ids.add(f"{entry.entry_id}_routines")

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # Clean up deprecated entities (e.g. redundant number.volume slider) and orphaned entities
    for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent_entry.domain == "number" and (
            ent_entry.unique_id.endswith("_device_volume")
            or ent_entry.unique_id.endswith("_volume")
        ):
            _LOGGER.info(
                "Removing deprecated volume number entity: %s", ent_entry.entity_id
            )
            ent_reg.async_remove(ent_entry.entity_id)
            continue

        # Check if entity belongs to an active device or structure
        dev_entry = (
            dev_reg.async_get(ent_entry.device_id) if ent_entry.device_id else None
        )
        if dev_entry:
            has_active_id = any(
                ident[0] == DOMAIN and ident[1] in active_device_ids
                for ident in dev_entry.identifiers
            )
            if not has_active_id:
                _LOGGER.info(
                    "Removing entity of unselected/orphaned Google Home device: %s (%s)",
                    ent_entry.entity_id,
                    ent_entry.unique_id,
                )
                ent_reg.async_remove(ent_entry.entity_id)
                continue

        # Check structure identifier in unique_id (e.g. scene, presence tracker, bridge)
        if "structure_" in ent_entry.unique_id:
            uid = ent_entry.unique_id
            # Extract structure id from unique_id
            is_valid_structure_entity = any(
                str(act_id) in uid for act_id in active_device_ids
            )
            if not is_valid_structure_entity:
                _LOGGER.info(
                    "Removing entity of unselected Google Home structure: %s (%s)",
                    ent_entry.entity_id,
                    ent_entry.unique_id,
                )
                ent_reg.async_remove(ent_entry.entity_id)

    # Mode-switch cleanup: remove stale control-entities or stale readonly sensors
    # depending on current third_party_mode
    from .const import (
        CONF_THIRD_PARTY_ENTITY_MODE,
        DEFAULT_THIRD_PARTY_ENTITY_MODE,
        THIRD_PARTY_MODE_READONLY,
    )

    third_party_mode = entry.options.get(
        CONF_THIRD_PARTY_ENTITY_MODE,
        entry.data.get(CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE),
    )

    # Controllable entity suffixes that should NOT exist in readonly mode for third-party devices
    CONTROL_SUFFIXES = (
        "_cloud_light",
        "_cloud_fan",
        "_cloud_switch",
        "_cloud_cover",
        "_cloud_vacuum",
        "_cloud_climate",
        "_cloud_lock",
        "_cloud_alarm",
        "_cloud_media",
    )

    if cloud_coordinator and cloud_coordinator.data:
        third_party_ids = {
            dev.device_id
            for dev in cloud_coordinator.data
            if dev.is_third_party and not dev.is_automation_routine
        }
        for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            uid = ent_entry.unique_id or ""
            if third_party_mode == THIRD_PARTY_MODE_READONLY:
                # Remove leftover control entities for third-party devices
                for dev_id in third_party_ids:
                    for suffix in CONTROL_SUFFIXES:
                        if uid == f"{dev_id}{suffix}":
                            _LOGGER.info(
                                "Removing stale control entity (mode=readonly): %s",
                                ent_entry.entity_id,
                            )
                            ent_reg.async_remove(ent_entry.entity_id)
                            break

    device_entries = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    for dev_entry in device_entries:
        # Check if device matches any active identifier
        has_active_id = any(
            ident[0] == DOMAIN and ident[1] in active_device_ids
            for ident in dev_entry.identifiers
        )
        if not has_active_id:
            _LOGGER.info(
                "Cleaning up orphaned Google Home device: %s (%s)",
                dev_entry.name,
                dev_entry.id,
            )
            # Remove any residual entities linked to this device
            for ent_entry in er.async_entries_for_device(ent_reg, dev_entry.id):
                ent_reg.async_remove(ent_entry.entity_id)
            # Remove the device itself
            dev_reg.async_remove_device(dev_entry.id)
        else:
            # Check if this is a structure or an actual device
            is_structure = any(
                ident[1].startswith(f"{entry.entry_id}_structure_")
                or ident[1].startswith("structure_")
                or ident[1].endswith("_hub")
                or ident[1].endswith("_routines")
                for ident in dev_entry.identifiers
                if ident[0] == DOMAIN
            )
            if is_structure:
                if dev_entry.sw_version:
                    dev_reg.async_update_device(dev_entry.id, sw_version=None)
            else:
                # Find matching device in local or cloud coordinator and sync sw_version / hw_version
                for ident in dev_entry.identifiers:
                    if ident[0] == DOMAIN:
                        dev_id = ident[1]
                        # 1. Local coordinator
                        if local_coordinator:
                            ldev = local_coordinator.get_device(dev_id)
                            if ldev and ldev.firmware_version:
                                dev_reg.async_update_device(
                                    dev_entry.id,
                                    sw_version=ldev.firmware_version,
                                    hw_version=ldev.hardware,
                                )
                                break
                        # 2. Cloud coordinator
                        if cloud_coordinator:
                            cdev = cloud_coordinator.get_device(dev_id)
                            if cdev and cdev.firmware_version:
                                dev_reg.async_update_device(
                                    dev_entry.id,
                                    sw_version=cdev.firmware_version,
                                    hw_version=cdev.hardware_version
                                    or cdev.hardware_model,
                                )
                                break


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow user to manually delete a device in Home Assistant UI if no longer present."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    local_coordinator = data.get(DATA_COORDINATOR)
    cloud_coordinator = data.get(DATA_CLOUD_COORDINATOR)

    active_device_ids: set[str] = set()
    if local_coordinator and local_coordinator.data:
        for dev in local_coordinator.data:
            active_device_ids.add(dev.device_id)

    if cloud_coordinator and cloud_coordinator.data:
        for cdev in cloud_coordinator.data:
            active_device_ids.add(cdev.device_id)
        active_device_ids.add(f"{entry.entry_id}_routines")

    # If any identifier belongs to active devices, prevent deletion
    for ident in device_entry.identifiers:
        if ident[0] == DOMAIN and ident[1] in active_device_ids:
            return False

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
        new_data = {**config_entry.data}
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        _LOGGER.info("Successfully migrated Google Home config entry to version 2")

    if config_entry.version == 2:
        username = config_entry.data.get(CONF_USERNAME)
        new_unique_id = username.strip().lower() if username else config_entry.unique_id
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
