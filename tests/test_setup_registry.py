"""Check setup cleanup against HA's registry with per-entry device identities."""

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.google_home import async_setup_entry
from custom_components.google_home.const import (
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    DOMAIN,
    MODE_CLOUD,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("own_fallback_exists", [False, True])
async def test_setup_removes_only_own_fallback_device(tmp_path, own_fallback_exists):
    """A matching identifier in another account must never be removed."""
    hass = HomeAssistant(str(tmp_path))

    def make_entry(entry_id):
        return ConfigEntry(
            domain=DOMAIN,
            entry_id=entry_id,
            title="Synthetic",
            data={CONF_OPERATION_MODE: MODE_CLOUD, CONF_MASTER_TOKEN: "synthetic"},
            options={},
            source="user",
            version=3,
            minor_version=1,
            unique_id=entry_id,
            discovery_keys=MappingProxyType({}),
            subentries_data=[],
        )

    own_entry, other_entry = make_entry("own"), make_entry("other")
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry.side_effect = {
        own_entry.entry_id: own_entry,
        other_entry.entry_id: other_entry,
    }.get
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    devices = dr.DeviceRegistry(hass)
    entities = er.EntityRegistry(hass)
    hass.data[dr.DATA_REGISTRY] = devices
    hass.data[er.DATA_REGISTRY] = entities
    await devices.async_load()
    await entities.async_load()

    identifier = (DOMAIN, "own_structure_default_home")

    def add_device(entry):
        return devices.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=None,
            identifiers={identifier},
            name="Default home",
        )

    other_device = add_device(other_entry)
    own_device = add_device(own_entry) if own_fallback_exists else None
    cloud_client = MagicMock(_cached_homes={"real-home": "Home"})
    coordinator = MagicMock(client=cloud_client, data=[])
    coordinator.async_config_entry_first_refresh = AsyncMock()

    try:
        with (
            patch("custom_components.google_home.async_get_clientsession"),
            patch(
                "custom_components.google_home.cloud_api.GoogleHomeCloudClient",
                return_value=cloud_client,
            ),
            patch(
                "custom_components.google_home.cloud_coordinator.GoogleHomeCloudDataUpdateCoordinator",
                return_value=coordinator,
            ),
            patch(
                "custom_components.google_home._async_cleanup_stale_devices_and_entities",
                new_callable=AsyncMock,
            ),
        ):
            assert await async_setup_entry(hass, own_entry)
        assert devices.async_get(other_device.id) == other_device
        if own_device is not None:
            assert own_device.id != other_device.id
            assert devices.async_get(own_device.id) is None
    finally:
        await hass.async_stop()
