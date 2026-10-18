"""Regress missing startup addresses and Do Not Disturb without a Cast entity."""

import asyncio
import threading
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    API_ENDPOINT_DO_NOT_DISTURB,
    DOMAIN,
    JSON_NOTIFICATIONS_ENABLED,
)
from custom_components.google_home.exceptions import DeviceConnectionError
from custom_components.google_home.local_discovery import (
    CastAddress,
    _AddressListener,
    discover_cast_addresses,
    normalize_cast_uuid,
)
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.switch import GoogleHomeDoNotDisturbSwitch

CAST_ID = "11111111222233334444555555555555"
OTHER_ID = "aaaaaaaa222233334444555555555555"
HOST = "192.0.2.10"


@pytest.fixture
async def local_client(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = ConfigEntry(
        domain=DOMAIN,
        title="Synthetic",
        data={},
        options={},
        source="user",
        version=3,
        minor_version=1,
        unique_id="synthetic",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    registry = dr.DeviceRegistry(hass)
    hass.data[dr.DATA_REGISTRY] = registry
    await registry.async_load()
    with patch("custom_components.google_home.api.GLocalAuthenticationTokens"):
        client = GlocaltokensApiClient(hass, MagicMock(), zeroconf_instance=MagicMock())
    client.get_access_token = AsyncMock(return_value="synthetic")
    client.async_get_available_homes = AsyncMock(return_value={})
    device = GoogleHomeDevice("office", "Office Display", "synthetic-token")
    client.google_devices = [device]
    try:
        yield client, device, registry, entry
    finally:
        await hass.async_stop()


def register(registry, entry, device_id="office", cast_ids=(CAST_ID,)):
    return registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=None,
        identifiers={(DOMAIN, device_id)} | {("cast", value) for value in cast_ids},
        name="Office Display",
    )


@pytest.mark.asyncio
async def test_dnd_recovers_ip_with_no_cast_entity(local_client):
    """Exercise the real switch, request transport and HA executor."""
    client, device, registry, entry = local_client
    register(registry, entry)
    response = MagicMock(status=200, content_type="application/json")
    response.json = AsyncMock(return_value={})
    client._session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    coordinator = MagicMock(client=client)
    coordinator.get_device.return_value = device
    switch = GoogleHomeDoNotDisturbSwitch(coordinator, device.device_id, device.name)
    switch.async_write_ha_state = MagicMock()
    event_loop_thread = threading.get_ident()

    def discover(zc):
        assert threading.get_ident() != event_loop_thread
        assert zc is client.zeroconf_instance
        return [CastAddress(HOST, CAST_ID, None)]

    with patch(
        "custom_components.google_home.api.discover_cast_addresses",
        side_effect=discover,
    ) as scan:
        await switch.async_turn_on()
        await switch.async_turn_off()
    assert device.ip_address == HOST
    assert device.cast_uuid == CAST_ID
    assert not device.get_do_not_disturb()
    assert not client.hass.states.async_all("media_player")
    assert scan.call_count == 1
    calls = client._session.request.call_args_list
    assert len(calls) == 2
    assert calls[0].args == (
        "POST",
        client.create_url(HOST, API_ENDPOINT_DO_NOT_DISTURB),
    )
    assert calls[0].kwargs["json"] == {JSON_NOTIFICATIONS_ENABLED: False}
    assert calls[1].kwargs["json"] == {JSON_NOTIFICATIONS_ENABLED: True}


@pytest.mark.asyncio
async def test_cached_missing_address_is_retried_on_later_poll(local_client):
    client, device, _, _ = local_client
    client._discovery_ids = {device.device_id: "homegraph-agent-id"}
    with patch(
        "custom_components.google_home.api.discover_cast_addresses",
        side_effect=[[], [CastAddress(HOST, CAST_ID, "homegraph-agent-id")]],
    ) as scan:
        assert await client.get_google_devices() == [device]
        assert device.ip_address is None
        await client.get_google_devices()
        assert scan.call_count == 1  # Immediate requests share a cooldown.
        client._last_address_discovery -= 31
        await client.get_google_devices()
    assert scan.call_count == 2
    assert device.ip_address == HOST
    client.get_access_token.assert_not_awaited()
    client._client.get_google_devices.assert_not_called()


@pytest.mark.asyncio
async def test_initial_scan_keeps_homegraph_discovery_identity(local_client):
    client, device, _, _ = local_client
    client.google_devices = []
    client._client.get_google_devices.return_value = [
        SimpleNamespace(
            device_id=device.device_id,
            device_name=device.name,
            local_auth_token=device.auth_token,
            ip_address=None,
            network_device=None,
            hardware="Google Nest Hub",
        )
    ]
    client._client.get_homegraph.return_value = SimpleNamespace(
        home=SimpleNamespace(
            devices=[
                SimpleNamespace(
                    device_info=SimpleNamespace(
                        device_id=device.device_id,
                        agent_info=SimpleNamespace(unique_id="homegraph-agent-id"),
                    )
                )
            ]
        )
    )
    with patch(
        "custom_components.google_home.api.discover_cast_addresses",
        return_value=[CastAddress(HOST, CAST_ID, "homegraph-agent-id")],
    ):
        devices = await client.get_google_devices()
    assert devices[0].device_id == device.device_id
    assert devices[0].ip_address == HOST
    assert devices[0].cast_uuid == CAST_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["no_identity", "foreign", "conflict", "ambiguous"])
async def test_does_not_assign_another_display_address(local_client, kind):
    client, device, registry, entry = local_client
    if kind == "foreign":
        register(registry, entry, device_id="different-display")
    elif kind == "conflict":
        register(registry, entry)
        client._discovery_ids[device.device_id] = "homegraph-agent-id"
    elif kind == "ambiguous":
        register(registry, entry, cast_ids=(CAST_ID, OTHER_ID))
    with patch(
        "custom_components.google_home.api.discover_cast_addresses",
        return_value=[CastAddress(HOST, OTHER_ID, "homegraph-agent-id")],
    ):
        with pytest.raises(DeviceConnectionError, match="after local discovery"):
            await client.set_do_not_disturb(device, True)
    assert device.ip_address is None
    assert not device.get_do_not_disturb()
    client._session.request.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_addresses_for_identity_are_not_guessed(local_client):
    client, device, _, _ = local_client
    device.cast_uuid = CAST_ID
    with patch(
        "custom_components.google_home.api.discover_cast_addresses",
        return_value=[
            CastAddress(HOST, CAST_ID, None),
            CastAddress("192.0.2.11", CAST_ID, None),
        ],
    ):
        await client.get_google_devices()
    assert device.ip_address is None


@pytest.mark.asyncio
async def test_concurrent_requests_share_scan(local_client):
    client, device, _, _ = local_client
    device.cast_uuid = CAST_ID
    with patch(
        "custom_components.google_home.api.discover_cast_addresses",
        return_value=[CastAddress(HOST, CAST_ID, None)],
    ) as scan:
        await asyncio.gather(*(client.get_google_devices() for _ in range(3)))
    assert scan.call_count == 1
    assert device.ip_address == HOST


@pytest.mark.asyncio
async def test_failed_scan_keeps_cached_device(local_client):
    client, device, _, _ = local_client
    with patch(
        "custom_components.google_home.api.discover_cast_addresses",
        side_effect=OSError("Synthetic discovery failure"),
    ):
        assert await client.get_google_devices() == [device]
    assert device.ip_address is None


@pytest.mark.asyncio
async def test_known_address_never_scans(local_client):
    client, device, _, _ = local_client
    device.ip_address = HOST
    with patch("custom_components.google_home.api.discover_cast_addresses") as scan:
        assert await client.get_google_devices() == [device]
    scan.assert_not_called()


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("bad", None),
        ("0" * 32, None),
        ("UUID:11111111-2222-3333-4444-555555555555", CAST_ID),
    ],
)
def test_normalize_cast_uuid(value, expected):
    assert normalize_cast_uuid(value) == expected


def test_listener_reads_uuid_and_discovery_id_separately():
    listener = _AddressListener()
    zc = MagicMock()
    zc.get_service_info.return_value = SimpleNamespace(
        properties={
            b"id": CAST_ID.encode(),
            b"cd": b"agent-id",
            b"md": b"Google Nest Hub",
        },
        parsed_scoped_addresses=lambda: ["fe80::1%2", HOST, "0.0.0.0", "invalid"],
    )
    listener.add_service(zc, "_googlecast._tcp.local.", "office")
    assert listener.devices["office"] == CastAddress(HOST, CAST_ID, "agent-id")
    listener.remove_service(zc, "_googlecast._tcp.local.", "office")
    assert not listener.devices


@pytest.mark.parametrize("addresses", [[], ["0.0.0.0", "224.0.0.1", "invalid"]])
def test_listener_ignores_unusable_addresses(addresses):
    listener = _AddressListener()
    zc = MagicMock()
    zc.get_service_info.return_value = SimpleNamespace(
        properties={b"id": CAST_ID.encode()},
        parsed_scoped_addresses=lambda: addresses,
    )
    listener.add_service(zc, "_googlecast._tcp.local.", "office")
    assert not listener.devices


def test_browser_is_cancelled_and_shared_zeroconf_stays_open():
    zc = MagicMock()
    with (
        patch(
            "custom_components.google_home.local_discovery.ServiceBrowser"
        ) as browser,
        patch("custom_components.google_home.local_discovery.Event") as event,
    ):
        assert discover_cast_addresses(zc) == []
    event.return_value.wait.assert_called_once_with(3)
    browser.return_value.cancel.assert_called_once()
    zc.close.assert_not_called()
