"""Test Google Home coordinator firmware syncing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.google_home.coordinator import GoogleHomeDataUpdateCoordinator
from custom_components.google_home.models import GoogleHomeDevice


@pytest.fixture(autouse=True)
def mock_coordinator_init(monkeypatch):
    """Mock DataUpdateCoordinator.__init__ to avoid frame helper check."""
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    def dummy_init(self, hass, logger, **kwargs):
        self.hass = hass
        self.logger = logger
        self.data = None
        self.config_entry = kwargs.get("config_entry")

    monkeypatch.setattr(DataUpdateCoordinator, "__init__", dummy_init)


@pytest.fixture
def mock_hass():
    """Mock HomeAssistant instance."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    return hass


@pytest.fixture
def mock_client():
    """Mock GlocaltokensApiClient."""
    client = MagicMock()
    client.update_google_devices_information = AsyncMock()
    return client


def test_coordinator_apply_firmware_to_device(mock_hass, mock_client):
    """Test matching firmware catalog entries to devices by hardware and name."""
    coord = GoogleHomeDataUpdateCoordinator(
        hass=mock_hass,
        client=mock_client,
        update_interval=120,
    )
    prod_versions = {
        "Google Nest Audio": {
            "firmware_version": "3.78.540761",
            "release_notes": "Improves network traffic",
        },
        "Google Home Mini": {
            "firmware_version": "3.78.540761",
            "release_notes": "Improves network traffic",
        },
        "Google Nest Hub (2nd gen)": {
            "firmware_version": "31.20260429.103.8712900",
            "release_notes": "Critical fixes",
        },
    }

    dev_audio = GoogleHomeDevice(
        device_id="dev1",
        name="Schlafzimmer Audio",
        auth_token="token",
        ip_address="192.168.1.10",
        hardware="Nest Audio",
    )
    dev_audio.set_system_info(firmware="3.75.000000")

    dev_hub = GoogleHomeDevice(
        device_id="dev2",
        name="Küche Display",
        auth_token="token",
        ip_address="192.168.1.11",
        hardware="Nest Hub (2nd gen)",
    )
    dev_hub.set_system_info(firmware="30.000000")

    dev_cast = GoogleHomeDevice(
        device_id="dev3",
        name="Küche Lautsprecher",
        auth_token="token",
        ip_address="192.168.1.12",
        hardware="Google Nest Mini",
    )
    dev_cast.set_system_info(
        firmware="1.68.cast_20251119_1643_RC14.834495410",
        latest_firmware="1.68.cast_20251119_1643_RC14.834495410",
    )

    coord._apply_firmware_to_device(dev_audio, prod_versions)
    assert dev_audio.latest_firmware_version == "3.78.540761"
    assert dev_audio.release_notes == "Improves network traffic"

    coord._apply_firmware_to_device(dev_hub, prod_versions)
    assert dev_hub.latest_firmware_version == "31.20260429.103.8712900"
    assert dev_hub.release_notes == "Critical fixes"

    coord._apply_firmware_to_device(dev_cast, prod_versions)
    assert dev_cast.latest_firmware_version == "1.68.cast_20251119_1643_RC14.834495410"


def test_coordinator_sync_firmware_versions_loads_remote(
    mock_hass, mock_client, monkeypatch
):
    """Test coordinator loads firmware json from remote URL on update."""
    coord = GoogleHomeDataUpdateCoordinator(
        hass=mock_hass,
        client=mock_client,
        update_interval=120,
    )

    dev = GoogleHomeDevice(
        device_id="dev_nest_audio",
        name="Wohnzimmer Nest Audio",
        auth_token="token",
        ip_address="192.168.1.20",
        hardware="Google Nest Audio",
    )
    dev.set_system_info(firmware="3.75.123456")

    remote_payload = '{"production": {"Google Nest Audio": {"firmware_version": "3.78.540761", "release_notes": "Fixes"}}}'

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=remote_payload)

    class MockContextManager:
        async def __aenter__(self):
            return mock_resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=MockContextManager())

    monkeypatch.setattr(
        "custom_components.google_home.coordinator.async_get_clientsession",
        lambda hass: mock_session,
    )

    asyncio.run(coord._async_sync_firmware_versions([dev]))

    assert coord._firmware_data is not None
    assert "production" in coord._firmware_data
    assert dev.latest_firmware_version == "3.78.540761"
    assert dev.release_notes == "Fixes"
