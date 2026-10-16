"""Linked service discovery, filtering, configuration, and safe registry cleanup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.google_home import (
    _async_cleanup_excluded_services,
    _async_cleanup_stale_devices_and_entities,
)
from custom_components.google_home.cloud_api import GoogleHomeCloudClient
from custom_components.google_home.config_flow import (
    GoogleHomeFlowHandler,
    GoogleHomeOptionsFlowHandler,
    _async_service_options,
)
from custom_components.google_home.const import (
    CONF_EXCLUDED_SERVICES,
    CONF_OPERATION_MODE,
    CONF_USERNAME,
    DATA_CLOUD_COORDINATOR,
    DOMAIN,
    MODE_HYBRID,
)


def raw_device(device_id, service_id=None, name="Living room light"):
    """Build a minimal HomeGraph device with independent provider identity."""
    return SimpleNamespace(
        device_info=SimpleNamespace(
            device_id=device_id,
            device_type="action.devices.types.LIGHT",
            agent_info=SimpleNamespace(api_project_id=service_id or ""),
        ),
        device_name=name,
        SerializeToString=lambda: b"home",
    )


@pytest.fixture
def cloud_client():
    """Use synthetic HomeGraph metadata and never contact Google."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn: fn())
    with patch("custom_components.google_home.cloud_api.GLocalAuthenticationTokens"):
        client = GoogleHomeCloudClient(hass, "synthetic", ignore_ha_synced=False)
    client._auth_client.get_homegraph.return_value = SimpleNamespace(
        home=SimpleNamespace(
            home_id="home",
            home_name="My Home",
            rooms=[],
            devices=[
                raw_device("lutron-light", "lutron-project"),
                raw_device("hue-light", "hue-project"),
                raw_device("unknown-light"),
            ],
        ),
        project_types=[
            SimpleNamespace(code="lutron-project", name="Lutron"),
            SimpleNamespace(code="hue-project", name="Philips Hue"),
        ],
    )
    client._get_available_homes_sync = MagicMock(return_value={"home": "My Home"})
    return client


@pytest.mark.asyncio
async def test_discover_services_including_excluded_provider(cloud_client):
    """An excluded provider remains discoverable so it can be re-enabled."""
    cloud_client.excluded_services = {"lutron-project"}
    assert await cloud_client.async_get_available_services() == {
        "lutron-project": "Lutron",
        "hue-project": "Philips Hue",
    }
    cloud_client.hass.async_add_executor_job.assert_awaited_once()


def test_filter_by_provider_id_and_restore(cloud_client):
    """Exclude a whole service despite renamed devices/providers, and restore it."""
    cloud_client.excluded_services = {"lutron-project"}
    graph = cloud_client._auth_client.get_homegraph.return_value
    graph.project_types[0].name = "Renamed Lutron service"
    devices = cloud_client._get_cloud_devices_sync()
    assert {d.device_id for d in devices} == {"hue-light", "unknown-light"}
    assert cloud_client.excluded_device_ids == {"lutron-light"}
    cloud_client.excluded_services.clear()
    assert len(cloud_client._get_cloud_devices_sync()) == 3
    assert cloud_client.excluded_device_ids == set()


def test_no_exclusions_preserves_existing_behavior(cloud_client):
    """Existing entries and devices without provider metadata remain included."""
    assert len(cloud_client._get_cloud_devices_sync()) == 3
    assert cloud_client.excluded_device_ids == set()


def test_all_devices_excluded_is_successful_empty_result(cloud_client):
    """An empty filtered result still records IDs needed for registry cleanup."""
    graph = cloud_client._auth_client.get_homegraph.return_value
    graph.home.devices = [raw_device("lutron-light", "lutron-project")]
    cloud_client.excluded_services = {"lutron-project"}
    assert cloud_client._get_cloud_devices_sync() == []
    assert cloud_client.excluded_device_ids == {"lutron-light"}


@pytest.mark.parametrize("field", ["agent_id", "unique_id"])
def test_provider_identity_fallbacks(cloud_client, field):
    """Google may expose an alternative ID or omit the project display name."""
    graph = cloud_client._auth_client.get_homegraph.return_value
    graph.project_types = []
    graph.home.devices = [raw_device("light", "")]
    graph.home.devices[0].device_info.agent_info = SimpleNamespace(
        **{field: "provider-project", "agent_name": "Provider"}
    )
    assert cloud_client._get_available_services_sync() == {
        "provider-project": "Provider"
    }


@pytest.mark.asyncio
async def test_service_options_preserve_saved_ids_during_outage():
    """Discovery errors cannot make previously excluded services unselectable."""
    client = MagicMock()
    client.async_get_available_services = AsyncMock(side_effect=TimeoutError)
    assert await _async_service_options(
        MagicMock(), None, None, ["lutron-project"], client
    ) == [{"value": "lutron-project", "label": "lutron-project"}]


@pytest.mark.asyncio
async def test_service_options_disambiguate_equal_names():
    """Equal display names are separate selectable providers with stable IDs."""
    client = MagicMock()
    client.async_get_available_services = AsyncMock(
        return_value={"service-b": "Lutron", "service-a": "Lutron"}
    )
    assert await _async_service_options(MagicMock(), None, None, [], client) == [
        {"value": "service-a", "label": "Lutron (service-a)"},
        {"value": "service-b", "label": "Lutron (service-b)"},
    ]


@pytest.mark.asyncio
async def test_setup_saves_excluded_services():
    """Initial setup stores selected provider IDs alongside the operation mode."""
    flow = GoogleHomeFlowHandler()
    flow.hass = MagicMock()
    flow._username = "user@example.com"
    with (
        patch.object(flow, "async_set_unique_id", new=AsyncMock()),
        patch.object(flow, "_abort_if_unique_id_configured"),
        patch.object(flow, "async_create_entry", return_value={}) as create,
    ):
        await flow.async_step_mode(
            {
                CONF_OPERATION_MODE: MODE_HYBRID,
                CONF_EXCLUDED_SERVICES: ["lutron-project"],
            }
        )
    assert create.call_args.kwargs["data"][CONF_EXCLUDED_SERVICES] == ["lutron-project"]


@pytest.mark.asyncio
async def test_setup_offers_discovered_services():
    """The setup form validates an exclusion selection using provider IDs."""
    flow = GoogleHomeFlowHandler()
    flow.hass = MagicMock()
    flow.hass.services.has_service.return_value = False
    with patch(
        "custom_components.google_home.config_flow._async_service_options",
        new=AsyncMock(return_value=[{"value": "lutron-project", "label": "Lutron"}]),
    ):
        result = await flow.async_step_mode()
    schema = result["data_schema"]
    validated = schema({CONF_EXCLUDED_SERVICES: ["lutron-project"]})
    assert validated[CONF_EXCLUDED_SERVICES] == ["lutron-project"]


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [[], ["lutron-project"]])
async def test_options_can_set_or_clear_exclusions(selection):
    """Explicitly clearing all exclusions overrides a saved setup selection."""
    flow = GoogleHomeOptionsFlowHandler()
    flow.hass = MagicMock()
    entry = SimpleNamespace(data={CONF_USERNAME: "user@example.com"})
    with (
        patch.object(
            GoogleHomeOptionsFlowHandler,
            "config_entry",
            new_callable=PropertyMock,
            return_value=entry,
        ),
        patch("custom_components.google_home.config_flow.async_get_clientsession"),
        patch.object(flow, "async_create_entry", return_value={}) as create,
    ):
        await flow.async_step_init({CONF_EXCLUDED_SERVICES: selection})
    assert create.call_args.kwargs["data"][CONF_EXCLUDED_SERVICES] == selection


@pytest.mark.asyncio
async def test_options_keep_excluded_services_in_form():
    """Excluded provider choices persist when filtered coordinator data is empty."""
    flow = GoogleHomeOptionsFlowHandler()
    flow.hass = MagicMock()
    flow.hass.services.has_service.return_value = False
    flow.hass.data = {}
    entry = SimpleNamespace(
        entry_id="entry",
        data={CONF_USERNAME: "user@example.com"},
        options={CONF_EXCLUDED_SERVICES: ["lutron-project"]},
    )
    with (
        patch.object(
            GoogleHomeOptionsFlowHandler,
            "config_entry",
            new_callable=PropertyMock,
            return_value=entry,
        ),
        patch("custom_components.google_home.config_flow.async_get_clientsession"),
    ):
        result = await flow.async_step_init()
    assert result["data_schema"]({})[CONF_EXCLUDED_SERVICES] == ["lutron-project"]


@pytest.fixture
def registry_state():
    """Model a shared device with native Lutron entities and Google duplicates."""
    entry = SimpleNamespace(entry_id="entry")
    entities = {
        "light.google_duplicate": SimpleNamespace(
            entity_id="light.google_duplicate",
            unique_id="lutron-light_cloud_light",
            config_entry_id="entry",
            device_id="shared",
        ),
        "sensor.google_status": SimpleNamespace(
            entity_id="sensor.google_status",
            unique_id="lutron-light_cloud_status",
            config_entry_id="entry",
            device_id="shared",
        ),
        "scene.google_routine": SimpleNamespace(
            entity_id="scene.google_routine",
            unique_id="lutron-routine_cloud_scene",
            config_entry_id="entry",
            device_id=None,
        ),
        "light.native_lutron": SimpleNamespace(
            entity_id="light.native_lutron",
            unique_id="native-lutron-light",
            config_entry_id="lutron-entry",
            device_id="shared",
        ),
        "light.google_hue": SimpleNamespace(
            entity_id="light.google_hue",
            unique_id="hue-light_cloud_light",
            config_entry_id="entry",
            device_id="hue",
        ),
    }
    ent_reg = MagicMock()
    ent_reg.async_remove.side_effect = entities.pop
    dev_reg = MagicMock()
    coordinator = SimpleNamespace(
        last_update_success=True,
        data=[],
        client=SimpleNamespace(excluded_device_ids={"lutron-light", "lutron-routine"}),
    )
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry": {DATA_CLOUD_COORDINATOR: coordinator}}}
    with (
        patch("custom_components.google_home.er.async_get", return_value=ent_reg),
        patch("custom_components.google_home.dr.async_get", return_value=dev_reg),
        patch(
            "custom_components.google_home.er.async_entries_for_config_entry",
            side_effect=lambda reg, eid: [
                e for e in entities.values() if e.config_entry_id == eid
            ],
        ),
        patch(
            "custom_components.google_home.er.async_entries_for_device",
            side_effect=lambda reg, did: [
                e for e in entities.values() if e.device_id == did
            ],
        ),
        patch(
            "custom_components.google_home.dr.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        yield hass, entry, coordinator, entities, dev_reg


@pytest.mark.asyncio
async def test_exclusions_clean_up_even_when_no_cloud_devices_remain(registry_state):
    """Remove only Google duplicates, including scenes, and preserve native entities."""
    hass, entry, _, entities, dev_reg = registry_state
    await _async_cleanup_stale_devices_and_entities(hass, entry)
    assert set(entities) == {"light.native_lutron", "light.google_hue"}
    dev_reg.async_remove_device.assert_not_called()
    dev_reg.async_update_device.assert_called_once_with(
        "shared", remove_config_entry_id="entry"
    )


def test_cleanup_waits_for_successful_discovery(registry_state):
    """A failed refresh must not remove entities based on stale exclusion metadata."""
    hass, entry, coordinator, entities, dev_reg = registry_state
    coordinator.last_update_success = False
    _async_cleanup_excluded_services(hass, entry, coordinator)
    assert len(entities) == 5
    dev_reg.async_update_device.assert_not_called()


def test_cleanup_keeps_device_with_other_entities_from_same_entry(registry_state):
    """Excluding cloud entities must not detach an active local speaker counterpart."""
    hass, entry, coordinator, entities, dev_reg = registry_state
    entities["sensor.local_alarm"] = SimpleNamespace(
        entity_id="sensor.local_alarm",
        unique_id="lutron-light_alarms",
        config_entry_id="entry",
        device_id="shared",
    )
    _async_cleanup_excluded_services(hass, entry, coordinator)
    assert "sensor.local_alarm" in entities
    dev_reg.async_update_device.assert_not_called()
