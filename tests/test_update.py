import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.update import GoogleHomeUpdateEntity


@pytest.fixture
def mock_coordinator():
    """Create a mock GoogleHomeDataUpdateCoordinator."""
    coord = MagicMock()
    coord.client = MagicMock()
    coord.client.reboot_device = AsyncMock(return_value={"success": True})
    coord.async_request_refresh = AsyncMock()
    return coord


def test_update_entity_properties(mock_coordinator):
    """Test update entity properties with up-to-date and pending updates."""
    dev = GoogleHomeDevice(
        device_id="audio_test",
        name="Nest Audio",
        auth_token="token_test",
        ip_address="192.168.1.100",
        hardware="Nest Audio",
    )
    dev.set_system_info(
        firmware="3.78.540761",
        mac="14:c1:4e:41:95:f8",
        cast_uuid="uuid123",
        ota_status="idle",
        latest_firmware="3.78.540761",
    )
    mock_coordinator.get_device = MagicMock(return_value=dev)

    entity = GoogleHomeUpdateEntity(
        coordinator=mock_coordinator,
        device_id=dev.device_id,
        device_name=dev.name,
    )

    assert entity.label == "firmware_update"
    assert entity.unique_id == "audio_test_firmware_update"
    assert entity.installed_version == "3.78.540761"
    assert "https://support.google.com/googlehome/answer/7365257" in (
        entity.release_url or ""
    )
    notes = asyncio.run(entity.async_release_notes())
    assert notes is not None
    assert "3.78.540761" in notes
    assert entity.in_progress is False
    assert entity.extra_state_attributes["hardware"] == "Nest Audio"
    assert entity.extra_state_attributes["ota_status"] == "idle"


def test_update_entity_progress_and_pending_update(mock_coordinator):
    """Test update entity with older version and active OTA download."""
    dev = GoogleHomeDevice(
        device_id="audio_test_2",
        name="Nest Audio",
        auth_token="token_test",
        ip_address="192.168.1.101",
        hardware="Nest Audio",
    )
    dev.set_system_info(
        firmware="3.75.000000",
        mac="14:c1:4e:41:95:f9",
        cast_uuid="uuid456",
        ota_status="downloading 45%",
        latest_firmware="3.78.540761",
    )
    mock_coordinator.get_device = MagicMock(return_value=dev)

    entity = GoogleHomeUpdateEntity(
        coordinator=mock_coordinator,
        device_id=dev.device_id,
        device_name=dev.name,
    )

    assert entity.installed_version == "3.75.000000"
    assert entity.latest_version == "3.78.540761"
    assert entity.in_progress is True
    assert entity.update_percentage == 45


def test_update_entity_async_install(mock_coordinator):
    """Test calling async_install sets installing state and reboots device."""
    dev = GoogleHomeDevice(
        device_id="audio_test",
        name="Nest Audio",
        auth_token="token_test",
        ip_address="192.168.1.100",
        hardware="Nest Audio",
    )
    mock_coordinator.get_device = MagicMock(return_value=dev)

    entity = GoogleHomeUpdateEntity(
        coordinator=mock_coordinator,
        device_id=dev.device_id,
        device_name=dev.name,
    )
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    asyncio.run(entity.async_install())
    mock_coordinator.client.reboot_device.assert_awaited_once_with(device=dev)
    assert entity.in_progress is True
    entity.hass.async_create_background_task.assert_called_once()
    # Close unawaited task coroutine created in test mock
    task_coro = entity.hass.async_create_background_task.call_args[0][0]
    task_coro.close()
