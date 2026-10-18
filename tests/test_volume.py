"""Regressions for startup media volume sources and delayed Google Cast states."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_VOLUME,
    DATA_CLOUD_COORDINATOR,
    DOMAIN,
    JSON_ALARM_VOLUME,
)
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.exceptions import DeviceConnectionError
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import (
    GoogleHomeAlarmVolumeNumber,
    GoogleHomeDeviceVolumeNumber,
)
from custom_components.google_home.volume import (
    read_volume_percentage,
    volume_percentage,
)


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"volume": 0}, 0),
        ({"level": 1}, 100),
        ({"current_volume": 0.23}, 23),
        ({"volume": 55}, 55),
        ({"volume": {"level": 0.55}}, 55),
        ({"volume": None, "current_volume": 0.55}, 55),
        ({"volume": "bad", "level": "0.55"}, 55),
        ({"volume": True}, None),
        ({"volume": -1}, None),
        ({"volume": float("nan")}, None),
        ({"volume": float("inf")}, None),
        ({"volume": 101}, None),
        ({}, None),
        (None, None),
    ],
)
def test_local_volume_payloads(payload, expected):
    """Accept supported response shapes and reject unusable telemetry."""
    assert read_volume_percentage(payload) == expected


def test_restored_one_percent_is_not_scaled_as_normalized_volume():
    """Restored slider values are already percentages, including values <= 1."""
    assert volume_percentage("1", normalized=False) == 1
    assert volume_percentage(1, normalized=True) == 100


@pytest.fixture
def device():
    return GoogleHomeDevice("speaker", "Kitchen", "synthetic", "192.0.2.10")


@pytest.fixture
def local_client():
    """Mock only transport; exercise the real endpoint and response selection."""
    client = object.__new__(GlocaltokensApiClient)
    for name in (
        "get_alarm_volume",
        "get_do_not_disturb",
        "get_night_mode_settings",
        "get_bluetooth_status",
        "get_eureka_info",
    ):
        setattr(client, name, AsyncMock(return_value={}))
    client.get_alarms_and_timers = AsyncMock(return_value={JSON_ALARM_VOLUME: 0.65})
    client._request = AsyncMock(return_value=None)
    client.get_direct_device_volume = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_current_volume_key_reaches_device_model(local_client, device):
    local_client._request.return_value = {"current_volume": 0.23}
    await local_client.update_device_data(device)
    assert device.get_device_volume() == 23
    assert device.get_alarm_volume() == 65
    assert device.device_volume_source == "local_api"


@pytest.mark.asyncio
@pytest.mark.parametrize("setup", [{}, {"tos_accepted": True}, {"tos_accepted": "yes"}])
async def test_cast_identity_is_read_independently_of_setup_consent(
    local_client, device, setup
):
    """A real Cast UUID must not be discarded when unrelated setup metadata is absent."""
    local_client.get_eureka_info.return_value = {
        "ssdp_udn": "uuid:11111111-2222-3333-4444-555555555555",
        "setup": setup,
    }
    await local_client.update_device_data(device)
    assert device.cast_uuid == "11111111222233334444555555555555"


@pytest.mark.asyncio
async def test_media_endpoint_fallback_never_uses_alarm_volume(local_client, device):
    async def request(method, device, endpoint):
        return {"volume": 0.65} if endpoint == API_ENDPOINT_ALARM_VOLUME else None

    local_client._request.side_effect = request
    assert await local_client.get_current_device_volume(device) is None
    assert all(
        call.args[2] != API_ENDPOINT_ALARM_VOLUME
        for call in local_client._request.call_args_list
    )


@pytest.mark.asyncio
async def test_failed_endpoint_does_not_skip_remaining_media_endpoints(
    local_client, device
):
    local_client._request.side_effect = [
        DeviceConnectionError("unreachable"),
        {"level": 0.23},
    ]
    assert await local_client.get_current_device_volume(device) == {"level": 0.23}
    assert local_client._request.call_count == 2


@pytest.mark.asyncio
async def test_invalid_payload_does_not_skip_remaining_endpoints(local_client, device):
    local_client._request.side_effect = [{"volume": "bad"}, {"current_volume": 0}]
    assert await local_client.get_current_device_volume(device) == {"current_volume": 0}


@pytest.mark.asyncio
async def test_eureka_is_fallback_and_cannot_overwrite_valid_zero(local_client, device):
    local_client._request.return_value = {"volume": 0}
    local_client.get_eureka_info.return_value = {"audio": {"volume": 0.70}}
    await local_client.update_device_data(device)
    assert device.get_device_volume() == 0
    assert device.device_volume_source == "local_api"
    local_client.get_direct_device_volume.assert_not_called()


@pytest.mark.asyncio
async def test_eureka_refreshes_previous_value_when_media_endpoints_fail(
    local_client, device
):
    device.set_device_volume(10)
    local_client.get_eureka_info.return_value = {"audio": {"current_volume": 0.70}}
    await local_client.update_device_data(device)
    assert device.get_device_volume() == 70
    assert device.device_volume_source == "eureka_audio"
    local_client.get_direct_device_volume.assert_not_called()


@pytest.mark.asyncio
async def test_direct_cast_refreshes_volume_each_poll_when_http_has_no_reading(
    local_client, device
):
    local_client.get_direct_device_volume.side_effect = [56, 21]
    await local_client.update_device_data(device)
    assert device.get_device_volume() == 56
    assert device.device_volume_source == "cast_direct"
    await local_client.update_device_data(device)
    assert device.get_device_volume() == 21
    assert local_client.get_direct_device_volume.call_count == 2


@pytest.mark.asyncio
async def test_failed_direct_poll_discards_stale_media_volume(local_client, device):
    device.set_device_volume(56, source="cast_direct")
    await local_client.update_device_data(device)
    assert device.get_device_volume() is None
    assert device.device_volume_source is None


@pytest.mark.asyncio
async def test_local_http_failure_does_not_prevent_direct_cast(local_client, device):
    local_client.get_alarms_and_timers.side_effect = DeviceConnectionError(
        "HTTP unavailable"
    )
    local_client.get_direct_device_volume.return_value = 56
    await local_client.update_device_data(device)
    assert device.get_device_volume() == 56
    assert device.device_volume_source == "cast_direct"


@pytest.mark.asyncio
async def test_direct_cast_does_not_require_a_google_auth_token(local_client, device):
    device.auth_token = None
    local_client.get_direct_device_volume.return_value = 56
    await local_client.update_device_data(device)
    assert device.get_device_volume() == 56
    local_client.get_alarms_and_timers.assert_not_called()


@pytest.mark.asyncio
async def test_direct_reader_error_does_not_discard_other_device_data(
    local_client, device
):
    device.cast_uuid = "11111111222233334444555555555555"
    device.set_device_volume(56, source="cast_direct")
    del local_client.get_direct_device_volume
    local_client.hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(side_effect=RuntimeError("reader failure"))
    )
    await local_client.update_device_data(device)
    assert device.get_alarm_volume() == 65
    assert device.get_device_volume() is None
    assert device.direct_cast_status == "unavailable"


@pytest.mark.asyncio
async def test_direct_cast_runs_off_event_loop_without_cast_entities(
    local_client, volume_entity, device, tmp_path
):
    """Exercise API -> real HA executor -> receiver reader -> volume slider."""
    entity, states, _ = volume_entity
    assert states == {}
    device.cast_uuid = "11111111222233334444555555555555"
    hass = HomeAssistant(str(tmp_path))
    local_client.hass = hass
    del local_client.get_direct_device_volume
    event_loop_thread = threading.get_ident()
    connection = MagicMock()

    def receiver_status():
        controller = connection.register_handler.call_args.args[0]
        controller.receive_message(
            None, {"type": "RECEIVER_STATUS", "status": {"volume": {"level": 0.56}}}
        )

    connection.start.side_effect = receiver_status

    def factory(*args, **kwargs):
        assert threading.get_ident() != event_loop_thread
        return connection

    try:
        with patch(
            "custom_components.google_home.local_cast.Chromecast", side_effect=factory
        ):
            await local_client.update_device_data(device)
        assert entity.native_value == 56
        attrs = entity.extra_state_attributes
        assert attrs["volume_source"] == "cast_direct"
        assert attrs["direct_cast_status"] == "ready"
        assert attrs["cast_volume"] is None
        assert attrs["media_player_entity_id"] is None
        assert attrs["local_volume"] == 56
        connection.disconnect.assert_called_once()
    finally:
        await hass.async_stop()


@pytest.mark.asyncio
async def test_failed_volume_write_does_not_change_live_cache(local_client, device):
    device.set_device_volume(23)
    local_client.set_device_volume = AsyncMock(return_value=None)
    await local_client.update_device_volume(device, 55)
    assert device.get_device_volume() == 23


@pytest.fixture
def volume_entity(device):
    coordinator = MagicMock()
    coordinator.get_device.return_value = device
    coordinator.config_entry = SimpleNamespace(entry_id="entry")
    entity = GoogleHomeDeviceVolumeNumber(coordinator, device.device_id, device.name)
    entity.entity_id = "number.kitchen_volume"
    entity.hass = MagicMock()
    entity.hass.data = {}
    states = {}
    entries = {}
    entity.hass.states.async_all.side_effect = lambda domain: list(states.values())
    entity.hass.states.get.side_effect = states.get
    registry = MagicMock()
    registry.async_get.side_effect = entries.get
    with patch(
        "custom_components.google_home.number.er.async_get", return_value=registry
    ):
        yield entity, states, entries


def add_cast(
    states,
    entries,
    *,
    entity_id="media_player.kitchen",
    name="Kitchen",
    volume=0.55,
    state="idle",
    platform="cast",
    restored=False,
    device_id=None,
    unique_id="cast-speaker",
):
    states[entity_id] = SimpleNamespace(
        entity_id=entity_id,
        state=state,
        attributes={
            "friendly_name": name,
            "volume_level": volume,
            "restored": restored,
        },
    )
    entries[entity_id] = SimpleNamespace(
        platform=platform, device_id=device_id, unique_id=unique_id
    )


@pytest.mark.asyncio
async def test_restored_value_never_enters_live_cache_or_masks_cast(
    volume_entity, device
):
    entity, states, entries = volume_entity
    add_cast(states, entries)
    with (
        patch.object(GoogleHomeBaseEntity, "async_added_to_hass", new=AsyncMock()),
        patch.object(
            entity,
            "async_get_last_state",
            new=AsyncMock(return_value=SimpleNamespace(state="40")),
        ),
        patch(
            "custom_components.google_home.number.async_track_state_change_filtered"
        ) as track,
    ):
        await entity.async_added_to_hass()
    assert device.get_device_volume() is None
    assert entity.native_value == 55
    assert entity.extra_state_attributes["restored_volume"] == 40
    assert entity.extra_state_attributes["volume_source"] == "google_cast"
    assert track.call_args.args[1].domains == {"media_player"}


def test_live_cast_overrides_cached_local_and_alarm_values(volume_entity, device):
    entity, states, entries = volume_entity
    device.set_device_volume(20)
    device.set_alarm_volume(65)
    entity._restored_value = 40
    add_cast(states, entries, volume=0.55)
    assert entity.native_value == 55


@pytest.mark.parametrize(
    "state,restored", [("unavailable", False), ("unknown", False), ("idle", True)]
)
def test_unavailable_or_restored_cast_cannot_override_live_local(
    volume_entity, device, state, restored
):
    entity, states, entries = volume_entity
    device.set_device_volume(23)
    add_cast(states, entries, volume=0.55, state=state, restored=restored)
    assert entity.native_value == 23
    assert entity.extra_state_attributes["volume_source"] == "local_api"


def test_alarm_volume_is_never_used_as_media_volume(volume_entity, device):
    entity, _, _ = volume_entity
    device.set_alarm_volume(65)
    assert entity.native_value is None
    entity._restored_value = 40
    assert entity.native_value == 40
    assert entity.extra_state_attributes["volume_source"] == "restored"


def test_alarm_slider_does_not_use_media_volume(volume_entity, device):
    media, _, _ = volume_entity
    alarm = GoogleHomeAlarmVolumeNumber(
        media.coordinator, device.device_id, device.name
    )
    device.set_device_volume(23)
    assert alarm.native_value is None
    alarm._restored_value = 40
    assert alarm.native_value == 40
    device.set_alarm_volume(65)
    assert alarm.native_value == 65


def test_cast_arriving_after_startup_updates_slider_without_poll(volume_entity):
    entity, states, entries = volume_entity
    entity._restored_value = 40
    entity.async_write_ha_state = MagicMock()
    assert entity.native_value == 40
    add_cast(states, entries)
    entity._async_cast_state_changed(
        SimpleNamespace(data={"entity_id": "media_player.kitchen"})
    )
    entity.async_write_ha_state.assert_called_once()
    assert entity.native_value == 55
    states.clear()
    entity._async_cast_state_changed(
        SimpleNamespace(data={"entity_id": "media_player.kitchen"})
    )
    assert entity.async_write_ha_state.call_count == 2
    assert entity.native_value == 40


def test_non_cast_and_substring_names_are_not_mistaken_for_target(volume_entity):
    entity, states, entries = volume_entity
    add_cast(
        states, entries, entity_id="media_player.kitchen_group", name="Kitchen group"
    )
    add_cast(
        states,
        entries,
        entity_id="media_player.own_cloud_entity",
        platform="google_home",
    )
    assert entity.native_value is None


def test_cloud_telemetry_is_never_used_as_local_volume(volume_entity):
    """Even a valid cloud value must not replace history on the local-only slider."""
    entity, states, entries = volume_entity
    entity._restored_value = 40
    cloud_device = SimpleNamespace(
        device_id=entity.device_id,
        name=entity.device_name,
        state={"currentVolume": 21},
    )
    entity.hass.data = {
        DOMAIN: {
            "entry": {DATA_CLOUD_COORDINATOR: SimpleNamespace(data=[cloud_device])}
        }
    }
    add_cast(
        states,
        entries,
        entity_id="media_player.office_office_display",
        name=entity.device_name,
        platform=DOMAIN,
        volume=0.21,
    )
    assert entity.native_value == 40
    assert entity.extra_state_attributes["volume_source"] == "restored"
    assert entity.extra_state_attributes["cast_status"] == "not_found"
    add_cast(states, entries, volume=0.21)
    assert entity.native_value == 21
    assert entity.extra_state_attributes["volume_source"] == "google_cast"
    assert entity.extra_state_attributes["cast_status"] == "ready"


def test_cast_uuid_matches_renamed_speaker(volume_entity, device):
    entity, states, entries = volume_entity
    device.cast_uuid = "1234-5678"
    add_cast(
        states,
        entries,
        entity_id="media_player.renamed",
        name="Renamed",
        unique_id="12345678",
    )
    assert entity.native_value == 55


def test_shared_device_matches_renamed_speaker(volume_entity):
    entity, states, entries = volume_entity
    entries[entity.entity_id] = SimpleNamespace(device_id="shared")
    add_cast(
        states,
        entries,
        entity_id="media_player.renamed",
        name="Renamed",
        device_id="shared",
    )
    assert entity.native_value == 55


def test_duplicate_cast_names_are_ambiguous_without_identity(volume_entity):
    entity, states, entries = volume_entity
    add_cast(states, entries, entity_id="media_player.one")
    add_cast(states, entries, entity_id="media_player.two")
    assert entity.native_value is None


def test_unrelated_cast_state_change_does_not_refresh_slider(volume_entity):
    entity, states, entries = volume_entity
    add_cast(states, entries)
    entity.async_write_ha_state = MagicMock()
    entity._async_cast_state_changed(
        SimpleNamespace(data={"entity_id": "media_player.other"})
    )
    entity.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
async def test_real_state_event_delivers_late_cast_reading(tmp_path, device):
    """Exercise HA's real domain-filtered listener and its removal without network I/O."""
    hass = HomeAssistant(str(tmp_path))
    coordinator = MagicMock()
    coordinator.get_device.return_value = device
    coordinator.config_entry = SimpleNamespace(entry_id="entry")
    entity = GoogleHomeDeviceVolumeNumber(coordinator, device.device_id, device.name)
    entity.entity_id = "number.kitchen_volume"
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    removers = []
    entity.async_on_remove = removers.append
    registry = MagicMock()
    registry.async_get.side_effect = lambda eid: (
        SimpleNamespace(platform="cast", device_id=None, unique_id="cast-speaker")
        if eid == "media_player.kitchen"
        else None
    )
    try:
        with (
            patch(
                "custom_components.google_home.number.er.async_get",
                return_value=registry,
            ),
            patch.object(GoogleHomeBaseEntity, "async_added_to_hass", new=AsyncMock()),
            patch.object(
                entity,
                "async_get_last_state",
                new=AsyncMock(return_value=SimpleNamespace(state="40")),
            ),
        ):
            await entity.async_added_to_hass()
            assert entity.native_value == 40
            hass.states.async_set(
                "media_player.kitchen",
                "idle",
                {
                    "friendly_name": "Kitchen",
                    "volume_level": 0.55,
                },
            )
            await hass.async_block_till_done()
            entity.async_write_ha_state.assert_called_once()
            assert entity.native_value == 55
            hass.states.async_set(
                "media_player.kitchen",
                "idle",
                {"friendly_name": "Kitchen", "volume_level": 0.21},
            )
            await hass.async_block_till_done()
            assert entity.async_write_ha_state.call_count == 2
            assert entity.native_value == 21
            for remove in removers:
                remove()
            hass.states.async_set(
                "media_player.kitchen",
                "idle",
                {
                    "friendly_name": "Kitchen",
                    "volume_level": 0.70,
                },
            )
            await hass.async_block_till_done()
            assert entity.async_write_ha_state.call_count == 2
    finally:
        await hass.async_stop()
