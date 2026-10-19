"""Resume backed-up repairs after interrupted device or entity registry writes."""

from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from custom_components.google_home.const import DOMAIN
from custom_components.google_home.registry_repair import async_repair_placeholder_macs
from tests.test_registry_repair import cloud_devices, merged_device
from tests.test_registry_repair import registries as registries


def add_entities(entities, entry, device_id):
    """Include disabled entities, whose associations must survive a failed repair."""
    return [
        entities.async_get_or_create(
            "number",
            DOMAIN,
            unique_id,
            config_entry=entry,
            config_subentry_id=None,
            device_id=device_id,
            disabled_by=er.RegistryEntryDisabler.USER,
        )
        for unique_id in ("laundry_volume", "guest_volume", "guest_alarm_volume")
    ]


async def repair_state(hass, entry):
    return await Store(
        hass, 1, f"{DOMAIN}_device_registry_repair.{entry.entry_id}"
    ).async_load()


@pytest.mark.asyncio
async def test_retry_after_destination_creation_failure_keeps_original_anchor(
    registries,
):
    hass, entry, devices, entities, _ = registries
    old = merged_device(devices, entry)
    original_entities = add_entities(entities, entry, old.id)
    with (
        patch.object(
            devices, "async_get_or_create", side_effect=RuntimeError("create failed")
        ),
        pytest.raises(RuntimeError, match="create failed"),
    ):
        await async_repair_placeholder_macs(hass, entry, cloud_devices())

    assert devices.async_get(old.id).identifiers == {(DOMAIN, "laundry")}
    assert (await repair_state(hass, entry))["pending"] == [old.id]
    models = cloud_devices()
    models[0].name = "Renamed laundry display"
    await async_repair_placeholder_macs(hass, entry, models)

    laundry = devices.async_get_device_by_identifier(
        (DOMAIN, "laundry"), entry.entry_id
    )
    guest = devices.async_get_device_by_identifier((DOMAIN, "guest"), entry.entry_id)
    assert laundry.id == old.id
    assert guest.id != old.id
    assert len(devices.devices) == 2
    for original in original_entities:
        current = entities.async_get(original.entity_id)
        assert current.unique_id == original.unique_id
        assert current.disabled_by == original.disabled_by
        assert current.device_id == (
            guest.id if original.unique_id.startswith("guest_") else laundry.id
        )
    assert (await repair_state(hass, entry))["pending"] == []


@pytest.mark.asyncio
async def test_retry_after_partial_entity_move_reuses_destination(registries):
    hass, entry, devices, entities, _ = registries
    old = merged_device(devices, entry)
    original_entities = add_entities(entities, entry, old.id)
    update_entity = entities.async_update_entity
    guest_moves = 0

    def interrupt_second_move(entity_id, **kwargs):
        nonlocal guest_moves
        guest_moves += 1
        if guest_moves == 2:
            raise RuntimeError("entity write failed")
        return update_entity(entity_id, **kwargs)

    with (
        patch.object(
            entities, "async_update_entity", side_effect=interrupt_second_move
        ),
        pytest.raises(RuntimeError, match="entity write failed"),
    ):
        await async_repair_placeholder_macs(hass, entry, cloud_devices())

    guest = devices.async_get_device_by_identifier((DOMAIN, "guest"), entry.entry_id)
    assert entities.async_get(original_entities[1].entity_id).device_id == guest.id
    assert entities.async_get(original_entities[2].entity_id).device_id == old.id
    device_ids = {device.id for device in devices.devices}
    await async_repair_placeholder_macs(hass, entry, cloud_devices())

    assert {device.id for device in devices.devices} == device_ids
    for original in original_entities:
        current = entities.async_get(original.entity_id)
        assert current.unique_id == original.unique_id
        assert current.disabled_by == original.disabled_by
        assert current.device_id == (
            guest.id if original.unique_id.startswith("guest_") else old.id
        )
    assert (await repair_state(hass, entry))["pending"] == []


@pytest.mark.asyncio
async def test_retry_rejects_unfamiliar_anchor_identity(registries):
    hass, entry, devices, entities, _ = registries
    old = merged_device(devices, entry)
    original_entities = add_entities(entities, entry, old.id)
    with (
        patch.object(
            devices, "async_get_or_create", side_effect=RuntimeError("create failed")
        ),
        pytest.raises(RuntimeError),
    ):
        await async_repair_placeholder_macs(hass, entry, cloud_devices())
    changed = devices.async_update_device(
        old.id, new_identifiers={(DOMAIN, "laundry"), (DOMAIN, "unfamiliar")}
    )
    await async_repair_placeholder_macs(hass, entry, cloud_devices())

    assert devices.async_get(old.id) == changed
    assert len(devices.devices) == 1
    assert all(
        entities.async_get(entity.entity_id) == entity for entity in original_entities
    )
    assert (await repair_state(hass, entry))["pending"] == [old.id]


@pytest.mark.asyncio
async def test_retry_does_not_reclaim_entity_reassigned_to_foreign_device(registries):
    hass, entry, devices, entities, _ = registries
    old = merged_device(devices, entry)
    original_entities = add_entities(entities, entry, old.id)
    with (
        patch.object(
            devices, "async_get_or_create", side_effect=RuntimeError("create failed")
        ),
        pytest.raises(RuntimeError),
    ):
        await async_repair_placeholder_macs(hass, entry, cloud_devices())
    foreign = devices.async_get_or_create(
        config_entry_id="foreign",
        config_subentry_id=None,
        identifiers={("other", "foreign-device")},
        name="Other integration device",
    )
    reassigned = entities.async_update_entity(
        original_entities[1].entity_id, device_id=foreign.id
    )
    current_anchor = devices.async_get(old.id)
    await async_repair_placeholder_macs(hass, entry, cloud_devices())

    assert devices.async_get(foreign.id) == foreign
    assert devices.async_get(old.id) == current_anchor
    assert entities.async_get(reassigned.entity_id) == reassigned
    assert (await repair_state(hass, entry))["pending"] == [old.id]


@pytest.mark.asyncio
async def test_retry_does_not_change_destination_with_disabled_foreign_entity(
    registries,
):
    hass, entry, devices, entities, _ = registries
    old = merged_device(devices, entry)
    original_entities = add_entities(entities, entry, old.id)
    with (
        patch.object(
            entities, "async_update_entity", side_effect=RuntimeError("move failed")
        ),
        pytest.raises(RuntimeError),
    ):
        await async_repair_placeholder_macs(hass, entry, cloud_devices())
    guest = devices.async_get_device_by_identifier((DOMAIN, "guest"), entry.entry_id)
    foreign_entry = hass.config_entries.async_get_entry("foreign")
    foreign_entity = entities.async_get_or_create(
        "sensor",
        "other",
        "foreign-entity",
        config_entry=foreign_entry,
        config_subentry_id=None,
        device_id=guest.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    await async_repair_placeholder_macs(hass, entry, cloud_devices())

    assert devices.async_get(guest.id) == guest
    assert entities.async_get(foreign_entity.entity_id) == foreign_entity
    assert all(
        entities.async_get(entity.entity_id) == entity for entity in original_entities
    )
    assert (await repair_state(hass, entry))["pending"] == [old.id]
