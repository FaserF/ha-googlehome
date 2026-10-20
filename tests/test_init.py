"""Test initialization repair followed by routine cleanup."""

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.google_home import _async_cleanup_stale_devices_and_entities
from custom_components.google_home.cloud_models import CloudHomeDevice
from custom_components.google_home.const import DATA_CLOUD_COORDINATOR, DOMAIN
from custom_components.google_home.registry_repair import async_repair_placeholder_macs


async def test_cleanup_merged_zero_mac_devices(hass: HomeAssistant) -> None:
    """Split both hardware identities and retain their entities through cleanup."""
    entry = MockConfigEntry(domain=DOMAIN, version=3, data={})
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    zero_mac = (dr.CONNECTION_NETWORK_MAC, "00:00:00:00:00:00")
    merged = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=None,
        identifiers={(DOMAIN, "device_1"), (DOMAIN, "device_2")},
        connections={zero_mac},
        name="First Display",
    )
    originals = [
        ent_reg.async_get_or_create(
            "number",
            DOMAIN,
            f"{device_id}_volume",
            config_entry=entry,
            config_subentry_id=None,
            device_id=merged.id,
            disabled_by=er.RegistryEntryDisabler.USER,
        )
        for device_id in ("device_1", "device_2")
    ]
    models = [
        CloudHomeDevice("device_1", "First Display", "action.devices.types.DISPLAY"),
        CloudHomeDevice("device_2", "Second Display", "action.devices.types.DISPLAY"),
    ]
    coordinator = MagicMock(data=models)
    coordinator.client.excluded_device_ids = set()
    coordinator.client._structure_alias_map = {}
    coordinator.get_device.side_effect = {
        model.device_id: model for model in models
    }.get
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_CLOUD_COORDINATOR: coordinator
    }

    # Setup performs backed-up identity repair before platforms and later cleanup.
    await async_repair_placeholder_macs(hass, entry, models)
    await _async_cleanup_stale_devices_and_entities(hass, entry)

    repaired = [
        dev_reg.async_get_device_by_identifier(
            (DOMAIN, model.device_id), entry.entry_id
        )
        for model in models
    ]
    assert repaired[0].id == merged.id
    assert repaired[1].id != merged.id
    for model, target, original in zip(models, repaired, originals, strict=True):
        assert target.identifiers == {(DOMAIN, model.device_id)}
        assert zero_mac not in target.connections
        current = ent_reg.async_get(original.entity_id)
        assert current.device_id == target.id
        assert current.unique_id == original.unique_id
        assert current.disabled_by == original.disabled_by
    snapshot = await Store(
        hass, 1, f"{DOMAIN}_device_registry_repair.{entry.entry_id}"
    ).async_load()
    assert merged.id in snapshot["backups"]
    assert snapshot["pending"] == []
