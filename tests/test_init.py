"""Test initialization and cleanup logic."""

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.google_home import _async_cleanup_stale_devices_and_entities
from custom_components.google_home.const import DOMAIN


async def test_cleanup_merged_zero_mac_devices(hass: HomeAssistant) -> None:
    """Test that historically merged zero-MAC devices are split apart."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Google Home",
        data={},
        source="user",
        options={},
        unique_id="user_id",
    )
    entry.add_to_hass(hass)

    dev_reg = dr.async_get(hass)

    # Create a device entry with multiple identifiers (mocking historical merge) and zero MAC connection
    dev_entry = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "device_1"), (DOMAIN, "device_2")},
        connections={(dr.CONNECTION_NETWORK_MAC, "00:00:00:00:00:00")},
        name="Merged Device",
    )

    assert len(dev_entry.identifiers) == 2
    assert (dr.CONNECTION_NETWORK_MAC, "00:00:00:00:00:00") in dev_entry.connections

    # Mock the active device ids in coordinator data
    l_dev1 = MagicMock()
    l_dev1.device_id = "device_1"
    l_dev1.structure_id = None
    l_dev1.firmware_version = "1.0"
    l_dev1.hardware = "Test"
    l_dev1.cast_uuid = None

    l_dev2 = MagicMock()
    l_dev2.device_id = "device_2"
    l_dev2.structure_id = None
    l_dev2.firmware_version = "1.0"
    l_dev2.hardware = "Test"
    l_dev2.cast_uuid = None

    coordinator_mock = MagicMock()
    coordinator_mock.data = [l_dev1, l_dev2]
    coordinator_mock.get_device = lambda x: l_dev1 if x == "device_1" else l_dev2

    data = {
        DOMAIN: {
            entry.entry_id: {
                "coordinator": coordinator_mock,
                "cloud_coordinator": None,
            }
        }
    }
    hass.data = data

    await _async_cleanup_stale_devices_and_entities(hass, entry)

    # Reload the device entry
    updated_entry = dev_reg.async_get(dev_entry.id)

    # It should now only have 1 identifier (the primary one)
    assert len(updated_entry.identifiers) == 1
    # It should not have the zero MAC connection
    assert not updated_entry.connections
