"""Device and entity cleanup routines for Google Home integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_THIRD_PARTY_ENTITY_MODE,
    DATA_CLOUD_COORDINATOR,
    DATA_COORDINATOR,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    THIRD_PARTY_MODE_READONLY,
    clean_mac_address,
    get_structure_url,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


def _async_cleanup_excluded_services(
    hass: HomeAssistant, entry: ConfigEntry, cloud_coordinator: Any
) -> None:
    """Remove only this entry's excluded cloud entities, preserving other integrations."""
    if cloud_coordinator is None or not cloud_coordinator.last_update_success:
        return
    excluded_ids = cloud_coordinator.client.excluded_device_ids
    if not excluded_ids:
        return

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    affected_devices: set[str] = set()
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = entity.unique_id
        if any(
            uid.startswith(f"{dev_id}_cloud_")
            or uid
            in (
                f"google_home_cloud_fan_{dev_id}",
                f"google_home_cloud_media_{dev_id}",
            )
            for dev_id in excluded_ids
        ):
            if entity.device_id:
                affected_devices.add(entity.device_id)
            ent_reg.async_remove(entity.entity_id)

    # Disabled entities may have been removed previously; also find registry-only devices.
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if any((DOMAIN, dev_id) in device.identifiers for dev_id in excluded_ids):
            affected_devices.add(device.id)

    for device_id in affected_devices:
        if not any(
            entity.config_entry_id == entry.entry_id
            for entity in er.async_entries_for_device(ent_reg, device_id)
        ):
            dev_reg.async_update_device(
                device_id, remove_config_entry_id=entry.entry_id
            )


async def _async_cleanup_stale_devices_and_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove devices and entities from registry that are no longer part of active coordinators."""
    from homeassistant.helpers import device_registry as dr

    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    local_coordinator = data.get(DATA_COORDINATOR)
    cloud_coordinator = data.get(DATA_CLOUD_COORDINATOR)

    # Run even when every cloud device is excluded and coordinator.data is empty.
    _async_cleanup_excluded_services(hass, entry, cloud_coordinator)

    # If any enabled coordinator is still in the process of its initial refresh, do not prune
    if (
        local_coordinator is not None
        and local_coordinator.last_update_success is False
        and not local_coordinator.data
    ):
        pass  # Failed initial refresh, proceed with available cloud data
    elif local_coordinator is not None and not local_coordinator.data:
        return
    if cloud_coordinator is not None and not cloud_coordinator.data:
        return
    if local_coordinator is None and cloud_coordinator is None:
        return

    active_device_ids: set[str] = set()
    active_structure_ids: set[str] = set()

    alias_map: dict[str, str] = {}
    if cloud_coordinator and hasattr(cloud_coordinator.client, "_structure_alias_map"):
        alias_map = cloud_coordinator.client._structure_alias_map

    if local_coordinator and local_coordinator.data:
        for dev in local_coordinator.data:
            active_device_ids.add(dev.device_id)
            if dev.structure_id:
                active_structure_ids.add(
                    alias_map.get(dev.structure_id, dev.structure_id)
                )

    if cloud_coordinator and cloud_coordinator.data:
        for cdev in cloud_coordinator.data:
            active_device_ids.add(cdev.device_id)
            if cdev.structure_id:
                canon_sid = alias_map.get(cdev.structure_id, cdev.structure_id)
                active_structure_ids.add(canon_sid)
                active_device_ids.add(f"{entry.entry_id}_structure_{canon_sid}")
                active_device_ids.add(f"structure_{canon_sid}")

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

        if "structure_" in uid or uid.startswith("google_home_presence_"):
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
            # Clean up any zero/placeholder MAC connections from the device registry entry (issue #8)
            cleaned_connections = {
                (conn_type, conn_val)
                for conn_type, conn_val in dev_entry.connections
                if conn_type != dr.CONNECTION_NETWORK_MAC
                or clean_mac_address(conn_val) is not None
            }
            if cleaned_connections != dev_entry.connections:
                _LOGGER.info(
                    "Removing placeholder/zero MAC connection from device %s (%s)",
                    dev_entry.name,
                    dev_entry.id,
                )
                dev_reg.async_update_device(
                    dev_entry.id,
                    new_connections=cleaned_connections,
                )

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
                # Extract structure_id from identifier
                struct_id = None
                for ident in dev_entry.identifiers:
                    if ident[0] == DOMAIN and "_structure_" in ident[1]:
                        struct_id = ident[1].split("_structure_")[-1]
                        break

                # Resolve structure_id to 64-char hex ID if present in available_homes
                if cloud_coordinator and struct_id:
                    avail_homes = (
                        await cloud_coordinator.client.async_get_available_homes()
                    )
                    struct_name = avail_homes.get(struct_id)
                    if struct_name:
                        for s_hex, s_n in avail_homes.items():
                            if s_n == struct_name and len(s_hex) == 64:
                                struct_id = s_hex
                                break

                dev_reg.async_update_device(
                    dev_entry.id,
                    sw_version=None,
                    configuration_url=get_structure_url(struct_id, "devices"),
                )
            else:
                # Find matching device in local or cloud coordinator and sync sw_version / hw_version / configuration_url
                for ident in dev_entry.identifiers:
                    if ident[0] == DOMAIN:
                        dev_id = ident[1]
                        # 1. Local coordinator
                        if local_coordinator:
                            ldev = local_coordinator.get_device(dev_id)
                            if ldev:
                                s_id = ldev.structure_id
                                if cloud_coordinator and s_id:
                                    avail_homes = await cloud_coordinator.client.async_get_available_homes()
                                    s_name = avail_homes.get(s_id)
                                    if s_name:
                                        for s_hex, s_n in avail_homes.items():
                                            if s_n == s_name and len(s_hex) == 64:
                                                s_id = s_hex
                                                break
                                dev_reg.async_update_device(
                                    dev_entry.id,
                                    sw_version=ldev.firmware_version,
                                    hw_version=ldev.hardware,
                                    configuration_url=get_structure_url(
                                        s_id, "devices"
                                    ),
                                )
                                # Merge with Google Cast device entry in Device Registry ONLY if not conflicting with MAC mapping
                                if getattr(ldev, "cast_uuid", None):
                                    c_uuid = str(ldev.cast_uuid).replace("-", "")
                                    cast_dev = None
                                    try:
                                        cast_dev = (
                                            dev_reg.async_get_device_by_identifier(  # type: ignore[call-arg]
                                                ("cast", c_uuid)
                                            )
                                        )
                                    except TypeError:
                                        # HA version requires config_entry_id — skip merge
                                        pass
                                    if cast_dev and cast_dev.id != dev_entry.id:
                                        _LOGGER.info(
                                            "Merging Cast device %s with Google Home device %s (%s)",
                                            cast_dev.name or cast_dev.id,
                                            dev_entry.name or dev_entry.id,
                                            c_uuid,
                                        )
                                        new_idents = set(dev_entry.identifiers) | {
                                            ("cast", c_uuid)
                                        }
                                        dev_reg.async_update_device(
                                            dev_entry.id,
                                            new_identifiers=new_idents,
                                        )
                                        for cast_ent in er.async_entries_for_device(
                                            ent_reg, cast_dev.id
                                        ):
                                            ent_reg.async_update_entity(
                                                cast_ent.entity_id,
                                                device_id=dev_entry.id,
                                            )
                                        try:
                                            dev_reg.async_remove_device(cast_dev.id)
                                        except Exception:
                                            pass
                                break
                        # 2. Cloud coordinator
                        if cloud_coordinator:
                            cdev = cloud_coordinator.get_device(dev_id)
                            if cdev:
                                s_id = cdev.structure_id
                                if s_id:
                                    # Use already-cached structure data from coordinator to avoid
                                    # blocking I/O in the event loop
                                    avail_homes = await cloud_coordinator.client.async_get_available_homes()
                                    s_name = avail_homes.get(s_id)
                                    if s_name:
                                        for s_hex, s_n in avail_homes.items():
                                            if s_n == s_name and len(s_hex) == 64:
                                                s_id = s_hex
                                                break
                                dev_reg.async_update_device(
                                    dev_entry.id,
                                    sw_version=cdev.firmware_version,
                                    hw_version=cdev.hardware_version
                                    or cdev.hardware_model,
                                    configuration_url=get_structure_url(
                                        s_id,
                                        "cameras" if cdev.is_camera else "devices",
                                    ),
                                )
                                break

    _async_sync_redundant_status_sensors(ent_reg, entry)


def _async_sync_redundant_status_sensors(
    ent_reg: er.EntityRegistry,
    entry: ConfigEntry,
) -> None:
    """Disable redundant cloud status sensors when control entities exist; re-enable if controls disappear."""
    control_prefix_to_dev: dict[str, str] = {}
    control_suffix_to_dev: dict[str, str] = {}
    status_sensor_entries: dict[str, list[er.RegistryEntry]] = {}

    for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = ent_entry.unique_id or ""
        if uid.endswith("_cloud_status"):
            dev_id = uid[: -len("_cloud_status")]
            status_sensor_entries.setdefault(dev_id, []).append(ent_entry)
            continue
        if uid.endswith("_cloud_nightlight_status"):
            dev_id = uid[: -len("_cloud_nightlight_status")]
            status_sensor_entries.setdefault(dev_id, []).append(ent_entry)
            continue

        if uid.startswith("google_home_cloud_fan_"):
            dev_id = uid[len("google_home_cloud_fan_") :]
            control_prefix_to_dev[dev_id] = uid
        elif uid.startswith("google_home_cloud_media_"):
            dev_id = uid[len("google_home_cloud_media_") :]
            control_prefix_to_dev[dev_id] = uid
        else:
            for suffix in (
                "_cloud_light",
                "_cloud_fan",
                "_cloud_switch",
                "_cloud_cover",
                "_cloud_vacuum",
                "_cloud_climate",
                "_cloud_lock",
                "_cloud_alarm",
                "_cloud_alarm_control_panel",
                "_cloud_media",
            ):
                if uid.endswith(suffix):
                    dev_id = uid[: -len(suffix)]
                    control_suffix_to_dev[dev_id] = uid
                    break

    controlled_device_ids = set(control_prefix_to_dev.keys()) | set(
        control_suffix_to_dev.keys()
    )

    for dev_id, status_ents in status_sensor_entries.items():
        has_control = dev_id in controlled_device_ids

        for status_ent in status_ents:
            if has_control:
                # Control entity exists: disable status sensor if active and not explicitly disabled/enabled by user
                if not status_ent.disabled:
                    _LOGGER.info(
                        "Disabling redundant status sensor for controlled device %s: %s",
                        dev_id,
                        status_ent.entity_id,
                    )
                    ent_reg.async_update_entity(
                        status_ent.entity_id,
                        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                    )
            else:
                # No control entity exists (e.g. local mode or readonly): re-enable if integration disabled it
                if (
                    status_ent.disabled
                    and status_ent.disabled_by == er.RegistryEntryDisabler.INTEGRATION
                ):
                    _LOGGER.info(
                        "Re-enabling status sensor as control entity is no longer present for device %s: %s",
                        dev_id,
                        status_ent.entity_id,
                    )
                    ent_reg.async_update_entity(
                        status_ent.entity_id,
                        disabled_by=None,
                    )
