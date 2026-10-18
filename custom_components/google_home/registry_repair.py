"""Repair device identities contaminated by placeholder MAC addresses (issue #8)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .cloud_models import CloudHomeDevice
from .const import DOMAIN, clean_mac_address
from .models import GoogleHomeDevice

_LOGGER = logging.getLogger(__name__)
type HomeDevice = GoogleHomeDevice | CloudHomeDevice


def _macs(device: HomeDevice) -> set[str]:
    """Collect usable hardware addresses without treating placeholders as identities."""
    values = [device.mac_address]
    if isinstance(device, GoogleHomeDevice):
        values.append(device.get_bluetooth_mac())
    return {dr.format_mac(mac) for value in values if (mac := clean_mac_address(value))}


def _cast_id(device: HomeDevice) -> str | None:
    value = getattr(device, "cast_uuid", None)
    if not isinstance(value, str):
        return None
    try:
        identity = UUID(value.lower().removeprefix("uuid:"))
    except ValueError:
        return None
    return identity.hex if identity.int else None


def _groups(devices: list[HomeDevice]) -> dict[str, set[str]]:
    """Keep local/cloud aliases together only when a real hardware key links them."""
    groups = {device.device_id: {device.device_id} for device in devices}
    keys: dict[tuple[str, str], str] = {}
    for device in devices:
        identities = {("mac", mac) for mac in _macs(device)}
        if cast_id := _cast_id(device):
            identities.add(("cast", cast_id))
        for identity in identities:
            if (other := keys.get(identity)) is not None:
                merged = groups[other] | groups[device.device_id]
                for member in merged:
                    groups[member] = merged
            keys[identity] = device.device_id
    return groups


def _entity_device_id(unique_id: str, device_ids: set[str]) -> str | None:
    """Resolve our entity formats; never infer a physical identity from its name."""
    for device_id in device_ids:
        if unique_id in (
            f"google_home_cloud_media_{device_id}",
            f"google_home_cloud_fan_{device_id}",
        ):
            return device_id
    for device_id in sorted(device_ids, key=lambda value: (-len(value), value)):
        if unique_id.startswith((f"{device_id}_", f"{device_id}/")):
            return device_id
    return None


def _exclusively_owned(device: dr.DeviceEntry, entry_id: str) -> bool:
    """Avoid changing a legacy shared/composite device's other integrations."""
    if owner := getattr(device, "config_entry_id", None):
        return owner == entry_id
    return device.config_entries == {entry_id}


async def async_repair_placeholder_macs(
    hass: HomeAssistant, entry: ConfigEntry, devices: list[HomeDevice]
) -> None:
    """Back up and repair before entity platforms start registering devices.

    Only split devices whose physical identities are all present in current data
    and whose registry entry is exclusively ours. Ambiguous cases retain their
    identifiers and are retried next setup; invalid MACs are removed immediately.
    """
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    store: Store[dict[str, Any]] = Store(
        hass, 1, f"{DOMAIN}_device_registry_repair.{entry.entry_id}"
    )
    saved = await store.async_load() or {"backups": {}, "pending": []}
    pending = set(saved["pending"])
    candidates = []
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        has_invalid_mac = any(
            kind == dr.CONNECTION_NETWORK_MAC and clean_mac_address(value) is None
            for kind, value in device.connections
        )
        if has_invalid_mac or device.id in pending:
            candidates.append(device)
            pending.add(device.id)
            saved["backups"].setdefault(
                device.id,
                {
                    "name": device.name,
                    "name_by_user": device.name_by_user,
                    "area_id": device.area_id,
                    "identifiers": sorted(device.identifiers),
                    "connections": sorted(device.connections),
                    "entities": {
                        entity.entity_id: {
                            "unique_id": entity.unique_id,
                            "platform": entity.platform,
                            "device_id": entity.device_id,
                        }
                        for entity in er.async_entries_for_device(
                            entities, device.id, include_disabled_entities=True
                        )
                    },
                },
            )
    if not candidates:
        return
    # Do not mutate a registry unless its recovery snapshot was saved successfully.
    saved["pending"] = sorted(pending)
    await store.async_save(saved)

    groups = _groups(devices)
    catalog = {device.device_id: device for device in devices}
    for old in candidates:
        clean_connections = {
            (kind, value)
            for kind, value in old.connections
            if kind != dr.CONNECTION_NETWORK_MAC or clean_mac_address(value) is not None
        }
        if clean_connections != old.connections:
            registry.async_update_device(old.id, new_connections=clean_connections)
        ids = {value for domain, value in old.identifiers if domain == DOMAIN}
        if len(ids) < 2:
            pending.discard(old.id)
            continue
        member_entities = er.async_entries_for_device(
            entities, old.id, include_disabled_entities=True
        )
        known_cast_ids = {
            cast_id
            for device in devices
            if device.device_id in ids and (cast_id := _cast_id(device))
        }
        safe = (
            ids <= catalog.keys()
            and _exclusively_owned(old, entry.entry_id)
            and all(
                entity.config_entry_id == entry.entry_id for entity in member_entities
            )
            and all(
                _entity_device_id(entity.unique_id, ids) is not None
                for entity in member_entities
            )
            and all(
                domain == DOMAIN
                or (
                    domain == "cast"
                    and value.replace("-", "").lower() in known_cast_ids
                )
                for domain, value in old.identifiers
            )
            and all(kind == dr.CONNECTION_NETWORK_MAC for kind, _ in old.connections)
        )
        if not safe:
            _LOGGER.warning(
                "Removed placeholder MACs from %s, but cannot safely split its device "
                "identities yet (missing device data or shared with another integration). "
                "The registry backup is in %s_device_registry_repair.%s; retry on reload "
                "when all Google devices are available",
                old.name or old.id,
                DOMAIN,
                entry.entry_id,
            )
            continue
        physical_groups = {frozenset(groups[device_id] & ids) for device_id in ids}
        if len(physical_groups) == 1:
            pending.discard(old.id)
            continue
        # A local/cloud ID mismatch without common hardware might be one device.
        # Require independent cloud records for every group, or distinct Cast IDs.
        cloud_ids = {
            device.device_id
            for device in devices
            if isinstance(device, CloudHomeDevice)
        }
        cast_ids = {
            device.device_id for device in devices if _cast_id(device) is not None
        }
        if not (
            all(group & cloud_ids for group in physical_groups)
            or all(group & cast_ids for group in physical_groups)
        ):
            _LOGGER.warning(
                "Deferring placeholder-MAC split for %s: local/cloud aliases cannot "
                "yet be distinguished; the registry backup has been retained",
                old.name or old.id,
            )
            continue
        # Keep the original device ID for the group matching its original name.
        ordered = sorted(
            physical_groups,
            key=lambda group: (
                not any(catalog[device_id].name == old.name for device_id in group),
                sorted(group),
            ),
        )
        targets: dict[str, str] = {}
        for index, group in enumerate(ordered):
            models = [model for model in devices if model.device_id in group]
            identifiers = {(DOMAIN, device_id) for device_id in group}
            identifiers.update(
                ("cast", cast_id) for model in models if (cast_id := _cast_id(model))
            )
            connections = {
                (dr.CONNECTION_NETWORK_MAC, mac)
                for model in models
                for mac in _macs(model)
            }
            if index == 0:
                registry.async_update_device(
                    old.id, new_identifiers=identifiers, new_connections=connections
                )
                target_id = old.id
            else:
                model = models[0]
                target = registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    config_subentry_id=getattr(old, "config_subentry_id", None),
                    identifiers=identifiers,
                    connections=connections,
                    name=model.name,
                    manufacturer=model.manufacturer,
                    model=model.model_name,
                    sw_version=model.firmware_version,
                    disabled_by=old.disabled_by,
                    suggested_area=next(
                        (
                            item.room_name
                            for item in models
                            if isinstance(item, CloudHomeDevice) and item.room_name
                        ),
                        None,
                    ),
                )
                target_id = target.id
            targets.update(dict.fromkeys(group, target_id))
        for entity in member_entities:
            if (device_id := _entity_device_id(entity.unique_id, ids)) is not None:
                target_id = targets[device_id]
                if entity.device_id != target_id:
                    entities.async_update_entity(entity.entity_id, device_id=target_id)
        pending.discard(old.id)
        _LOGGER.warning(
            "Repaired placeholder-MAC merge for %s: separated %s devices and kept "
            "entity IDs. Review areas and automations that target the old device ID",
            old.name or old.id,
            len(ordered),
        )
    saved["pending"] = sorted(pending)
    await store.async_save(saved)
