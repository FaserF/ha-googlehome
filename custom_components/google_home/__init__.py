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
    AUTH_METHOD_TOKEN,
    CONF_ANDROID_ID,
    CONF_AUTH_METHOD,
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
    DEFAULT_LOCAL_UPDATE_INTERVAL,
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
    # Retrieve polling intervals: local (default 120s, min 60s), cloud (default 300s, min 60s)

    legacy_interval = entry.options.get(
        CONF_UPDATE_INTERVAL,
        entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
    )
    local_update_interval = entry.options.get(
        CONF_LOCAL_UPDATE_INTERVAL,
        entry.data.get(
            CONF_LOCAL_UPDATE_INTERVAL,
            legacy_interval if legacy_interval != 60 else DEFAULT_LOCAL_UPDATE_INTERVAL,
        ),
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
    # 0. Migrate legacy leikoilja entity unique_ids before setting up platforms
    # This ensures new platform entities match the existing registry entries and keep entity_ids & names
    ent_reg = er.async_get(hass)
    for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = ent_entry.unique_id or ""
        # Handle deprecated leikoilja device sensor (e.g. '<device_id>/device' or '<device_id>_device')
        if uid.endswith("/device") or uid.endswith("_device"):
            _LOGGER.info(
                "Removing deprecated legacy device sensor entity: %s (%s)",
                ent_entry.entity_id,
                uid,
            )
            ent_reg.async_remove(ent_entry.entity_id)
            continue

        # Map leikoilja unique_ids:
        # '<device_id>/alarms' -> '<device_id>_alarms'
        # '<device_id>/timers' -> '<device_id>_timers'
        # '<device_id>/alarm volume' or '<device_id>_alarm volume' -> '<device_id>_alarm_volume'
        # '<device_id>/Do Not Disturb' or '<device_id>_Do Not Disturb' -> '<device_id>_do_not_disturb'
        new_uid = uid.replace("/", "_")
        if new_uid.endswith("_alarm volume"):
            new_uid = new_uid.replace("_alarm volume", "_alarm_volume")
        elif new_uid.endswith("_Do Not Disturb") or new_uid.endswith("_do not disturb"):
            new_uid = new_uid.replace("_Do Not Disturb", "_do_not_disturb").replace(
                "_do not disturb", "_do_not_disturb"
            )

        if new_uid != uid:
            existing_new_ent = ent_reg.async_get_entity_id(
                ent_entry.domain, DOMAIN, new_uid
            )
            if existing_new_ent and existing_new_ent != ent_entry.entity_id:
                _LOGGER.info(
                    "Removing duplicate newer entity %s to restore migrated entity %s",
                    existing_new_ent,
                    ent_entry.entity_id,
                )
                ent_reg.async_remove(existing_new_ent)

            _LOGGER.info(
                "Migrating entity unique_id '%s' -> '%s' for %s",
                uid,
                new_uid,
                ent_entry.entity_id,
            )
            try:
                ent_reg.async_update_entity(ent_entry.entity_id, new_unique_id=new_uid)
            except Exception as err:
                _LOGGER.warning(
                    "Could not migrate entity unique_id for %s: %s",
                    ent_entry.entity_id,
                    err,
                )

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
    active_structure_ids: set[str] = set()

    if local_coordinator and local_coordinator.data:
        for dev in local_coordinator.data:
            active_device_ids.add(dev.device_id)
            if dev.structure_id:
                active_structure_ids.add(dev.structure_id)

    if cloud_coordinator and cloud_coordinator.data:
        for cdev in cloud_coordinator.data:
            active_device_ids.add(cdev.device_id)
            if cdev.structure_id:
                active_structure_ids.add(cdev.structure_id)
                active_device_ids.add(f"{entry.entry_id}_structure_{cdev.structure_id}")
                active_device_ids.add(f"structure_{cdev.structure_id}")

    for sid in active_structure_ids:
        active_device_ids.add(f"{entry.entry_id}_structure_{sid}")
        active_device_ids.add(f"structure_{sid}")

    active_device_ids.add(f"{entry.entry_id}_hub")
    active_device_ids.add(f"{entry.entry_id}_routines")

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # Clean up deprecated entities and orphaned entities
    for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = ent_entry.unique_id or ""
        # Remove deprecated leikoilja device sensor (e.g. '<device_id>_device')
        if uid.endswith("/device") or uid.endswith("_device"):
            _LOGGER.info(
                "Removing deprecated legacy device sensor entity: %s (%s)",
                ent_entry.entity_id,
                uid,
            )
            ent_reg.async_remove(ent_entry.entity_id)
            continue

        # 1. Check if entity belongs to an active device
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

        # 2. Check entities without device_entry or scene/routine/structure unique_ids
        uid = ent_entry.unique_id or ""
        if ent_entry.domain == "scene" or "_cloud_scene" in uid:
            # Check if routine device_id is still present in active coordinator data
            is_active_scene = any(act_id in uid for act_id in active_device_ids)
            if not is_active_scene:
                _LOGGER.info(
                    "Removing scene of unselected Google Home: %s (%s)",
                    ent_entry.entity_id,
                    uid,
                )
                ent_reg.async_remove(ent_entry.entity_id)
                continue

        if "structure_" in uid:
            is_valid_structure_entity = any(sid in uid for sid in active_structure_ids)
            if not is_valid_structure_entity:
                _LOGGER.info(
                    "Removing entity of unselected Google Home structure: %s (%s)",
                    ent_entry.entity_id,
                    uid,
                )
                ent_reg.async_remove(ent_entry.entity_id)
                continue

        # Fallback check for any orphaned entity whose unique_id starts with a deleted device_id
        is_active_entity = any(act_id in uid for act_id in active_device_ids)
        if not is_active_entity and not dev_entry:
            _LOGGER.info(
                "Removing orphaned entity: %s (%s)",
                ent_entry.entity_id,
                uid,
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

    # Clean up deprecated set_timer and set_alarm entities
    for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = ent_entry.unique_id or ""
        if uid.endswith("_set_timer") or uid.endswith("_set_alarm"):
            _LOGGER.info(
                "Removing deprecated speaker timer/alarm scheduling entity (%s): %s",
                uid,
                ent_entry.entity_id,
            )
            ent_reg.async_remove(ent_entry.entity_id)

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
        local_update_interval = max(60, legacy_update_interval)

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
        _LOGGER.info(
            "Successfully auto-migrated leikoilja entry to VERSION=3 "
            "(auth_method=%s, mode=%s, unique_id=%s)",
            auth_method,
            MODE_LOCAL,
            new_unique_id,
        )
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
