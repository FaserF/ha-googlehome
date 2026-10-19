"""Use real HA registries to regress issue #8 and preserve entity identities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.google_home.cloud_models import CloudHomeDevice
from custom_components.google_home.const import DOMAIN, clean_mac_address
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import GoogleHomeDeviceVolumeNumber
from custom_components.google_home.registry_repair import (
    _entity_device_id,
    async_repair_placeholder_macs,
)

ZERO = (dr.CONNECTION_NETWORK_MAC, "00:00:00:00:00:00")


def config_entry(entry_id="google", domain=DOMAIN):
    return MockConfigEntry(
        domain=domain,
        entry_id=entry_id,
        title="Synthetic test",
        data={},
        options={},
        source="user",
        version=3,
        minor_version=1,
        unique_id=entry_id,
    )


@pytest.fixture
def registries(hass, device_registry, entity_registry, area_registry):
    entry = config_entry()
    foreign = config_entry("foreign", "other")
    entry.add_to_hass(hass)
    foreign.add_to_hass(hass)
    return hass, entry, device_registry, entity_registry, area_registry


def cloud_devices():
    return [
        CloudHomeDevice(
            "laundry",
            "Laundry Display",
            "action.devices.types.DISPLAY",
            room_name="Laundry",
        ),
        CloudHomeDevice(
            "guest", "Guest Display", "action.devices.types.DISPLAY", room_name="Guest"
        ),
    ]


def merged_device(devices, entry, *, identifiers=None, connections=None):
    return devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=None,
        identifiers=identifiers or {(DOMAIN, "laundry"), (DOMAIN, "guest")},
        connections={ZERO} if connections is None else connections,
        name="Laundry Display",
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "00:00:00:00:00:00",
        "00-00-00-00-00-00",
        "000000000000",
        "0000.0000.0000",
        " 0000.0000.0000 ",
        ":".join(["ff"] * 6),
        "FFFFFFFFFFFF",
        "ffff.ffff.ffff",
        "GG:GG:GG:GG:GG:GG",
        "02:00:00:00:00:01:02",
        "1234567890a",
        "1234567890abc",
        "not a mac address",
        123456789012,
    ],
)
def test_reject_unusable_mac_connections(value):
    assert clean_mac_address(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "02:00:00:00:00:01",
        "AA:BB:CC:DD:EE:FF",
        "020000000001",
        "0200.0000.0001",
        "02-00-00-00-00-01",
    ],
)
def test_keep_real_mac_formats(value):
    assert clean_mac_address(value) == value


def test_cloud_unique_ids_take_precedence_over_a_similar_device_id_prefix():
    assert (
        _entity_device_id("google_home_cloud_media_guest", {"google", "guest"})
        == "guest"
    )
    assert (
        _entity_device_id("guest_long_volume", {"guest", "guest_long"}) == "guest_long"
    )


def test_device_info_filters_dotted_zero_and_uses_valid_bluetooth_fallback():
    device = GoogleHomeDevice("speaker", "Display", "synthetic")
    device.mac_address = "0000.0000.0000"
    coordinator = MagicMock()
    coordinator.get_device.return_value = device
    entity = GoogleHomeDeviceVolumeNumber(coordinator, device.device_id, device.name)
    assert entity.device_info["connections"] == set()
    device.set_bluetooth_mac("02:00:00:00:00:01")
    assert entity.device_info["connections"] == {("mac", "02:00:00:00:00:01")}


@pytest.mark.asyncio
async def test_remove_old_zero_connection_and_split_without_replacing_entities(
    registries,
):
    hass, entry, devices, entities, areas = registries
    old = merged_device(devices, entry)
    area = areas.async_get_or_create("User area")
    devices.async_update_device(old.id, area_id=area.id, name_by_user="My display")
    before = {}
    for device_id in ("laundry", "guest"):
        for domain, uid in (
            ("number", f"{device_id}_volume"),
            ("media_player", f"google_home_cloud_media_{device_id}"),
        ):
            entity = entities.async_get_or_create(
                domain,
                DOMAIN,
                uid,
                config_entry=entry,
                config_subentry_id=None,
                device_id=old.id,
                disabled_by=er.RegistryEntryDisabler.USER,
                original_name=f"{device_id} volume",
            )
            before[entity.entity_id] = entity
    # Reproduce why the old cleanup didn't work: merging an empty set removes nothing.
    with patch("homeassistant.helpers.device_registry.report_usage"):
        devices.async_update_device(old.id, merge_connections=set())
    assert ZERO in devices.async_get(old.id).connections
    await async_repair_placeholder_macs(hass, entry, cloud_devices())
    laundry = devices.async_get_device_by_identifier(
        (DOMAIN, "laundry"), entry.entry_id
    )
    guest = devices.async_get_device_by_identifier((DOMAIN, "guest"), entry.entry_id)
    assert laundry.id == old.id
    assert guest.id != laundry.id
    assert laundry.area_id == area.id
    assert laundry.name_by_user == "My display"
    assert ZERO not in laundry.connections
    assert ZERO not in guest.connections
    assert len(entities.entities) == len(before)
    for entity_id, previous in before.items():
        current = entities.async_get(entity_id)
        assert current.unique_id == previous.unique_id
        assert current.disabled_by == previous.disabled_by
        expected = guest.id if "guest" in previous.unique_id else laundry.id
        assert current.device_id == expected, (
            entity_id,
            previous.unique_id,
            laundry.id,
            guest.id,
        )
    snapshot = await Store(
        hass, 1, f"{DOMAIN}_device_registry_repair.{entry.entry_id}"
    ).async_load()
    assert snapshot["pending"] == []
    assert ["mac", "00:00:00:00:00:00"] in snapshot["backups"][old.id]["connections"]
    assert set(snapshot["backups"][old.id]["entities"]) == set(before)
    device_ids = {device.id for device in devices.devices}
    await async_repair_placeholder_macs(hass, entry, cloud_devices())
    assert {device.id for device in devices.devices} == device_ids


@pytest.mark.asyncio
async def test_clean_single_device_before_another_can_match_its_zero_mac(registries):
    hass, entry, devices, _, _ = registries
    old = merged_device(devices, entry, identifiers={(DOMAIN, "laundry")})
    await async_repair_placeholder_macs(hass, entry, cloud_devices())
    assert devices.async_get(old.id).connections == set()
    added = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=None,
        identifiers={(DOMAIN, "guest")},
        connections=set(),
        name="Guest Display",
    )
    assert added.id != old.id


@pytest.mark.asyncio
async def test_local_and_cloud_aliases_with_a_real_shared_mac_stay_together(registries):
    hass, entry, devices, _, _ = registries
    old = merged_device(devices, entry)
    models = cloud_devices()
    for model in models:
        model.mac_address = "02:00:00:00:00:01"
    await async_repair_placeholder_macs(hass, entry, models)
    assert devices.async_get(old.id).identifiers == old.identifiers
    assert len(devices.devices) == 1
    assert ZERO not in devices.async_get(old.id).connections


@pytest.mark.asyncio
async def test_partial_discovery_defers_split_then_retries_after_zero_is_removed(
    registries,
):
    hass, entry, devices, _, _ = registries
    old = merged_device(devices, entry)
    await async_repair_placeholder_macs(hass, entry, cloud_devices()[:1])
    assert devices.async_get(old.id).identifiers == old.identifiers
    assert ZERO not in devices.async_get(old.id).connections
    await async_repair_placeholder_macs(hass, entry, cloud_devices())
    assert len(devices.devices) == 2


@pytest.mark.asyncio
async def test_foreign_identifiers_defer_split_and_other_integrations_are_untouched(
    registries,
):
    hass, entry, devices, _, _ = registries
    old = merged_device(
        devices,
        entry,
        identifiers={(DOMAIN, "laundry"), (DOMAIN, "guest"), ("other", "foreign-id")},
    )
    other = devices.async_get_or_create(
        config_entry_id="foreign",
        config_subentry_id=None,
        identifiers={("other", "untouched")},
        connections={ZERO},
        name="Other integration",
    )
    await async_repair_placeholder_macs(hass, entry, cloud_devices())
    assert devices.async_get(old.id).identifiers == old.identifiers
    assert ZERO not in devices.async_get(old.id).connections
    assert devices.async_get(other.id).connections == {ZERO}


@pytest.mark.asyncio
async def test_backup_failure_prevents_any_registry_mutation(registries):
    hass, entry, devices, _, _ = registries
    old = merged_device(devices, entry)
    store = SimpleNamespace(
        async_load=AsyncMock(return_value=None),
        async_save=AsyncMock(side_effect=OSError("disk unavailable")),
    )
    with (
        patch(
            "custom_components.google_home.registry_repair.Store", return_value=store
        ),
        pytest.raises(OSError),
    ):
        await async_repair_placeholder_macs(hass, entry, cloud_devices())
    assert devices.async_get(old.id) == old


@pytest.mark.asyncio
async def test_ambiguous_local_cloud_aliases_are_not_split(registries):
    hass, entry, devices, _, _ = registries
    old = merged_device(devices, entry)
    models = [
        cloud_devices()[0],
        GoogleHomeDevice("guest", "Laundry Display", "synthetic"),
    ]
    await async_repair_placeholder_macs(hass, entry, models)
    assert devices.async_get(old.id).identifiers == old.identifiers
    assert len(devices.devices) == 1


@pytest.mark.asyncio
async def test_shared_registry_entry_with_disabled_foreign_entity_is_not_split(
    registries,
):
    hass, entry, devices, entities, _ = registries
    old = merged_device(devices, entry)
    foreign_entry = hass.config_entries.async_get_entry("foreign")
    foreign_entity = entities.async_get_or_create(
        "sensor",
        "other",
        "foreign-volume",
        config_entry=foreign_entry,
        config_subentry_id=None,
        device_id=old.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    await async_repair_placeholder_macs(hass, entry, cloud_devices())
    assert devices.async_get(old.id).identifiers == old.identifiers
    assert entities.async_get(foreign_entity.entity_id) == foreign_entity


@pytest.mark.asyncio
async def test_local_cast_identities_are_redistributed_without_touching_cast_device(
    registries,
):
    hass, entry, devices, entities, areas = registries
    models = [
        GoogleHomeDevice("laundry", "Laundry Display", "synthetic"),
        GoogleHomeDevice("guest", "Guest Display", "synthetic"),
    ]
    models[0].cast_uuid = "11111111222233334444555555555555"
    models[1].cast_uuid = "66666666777788889999aaaaaaaaaaaa"
    identifiers = {(DOMAIN, model.device_id) for model in models} | {
        ("cast", model.cast_uuid) for model in models
    }
    old = merged_device(devices, entry, identifiers=identifiers)
    cast_device = devices.async_get_or_create(
        config_entry_id="foreign",
        config_subentry_id=None,
        identifiers={("cast", models[1].cast_uuid)},
        name="Native Cast device",
    )
    for model in models:
        entities.async_get_or_create(
            "number",
            DOMAIN,
            f"{model.device_id}_volume",
            config_entry=entry,
            config_subentry_id=None,
            device_id=old.id,
        )
    await async_repair_placeholder_macs(hass, entry, models + cloud_devices())
    guest = devices.async_get_device_by_identifier((DOMAIN, "guest"), entry.entry_id)
    assert guest.id != old.id
    assert ("cast", models[1].cast_uuid) in guest.identifiers
    assert ("cast", models[1].cast_uuid) not in devices.async_get(old.id).identifiers
    assert devices.async_get(cast_device.id) == cast_device
    assert areas.async_get_area(guest.area_id).name == "Guest"
