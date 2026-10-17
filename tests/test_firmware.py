"""Regression tests for separate Cast and Nest display system firmware."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.coordinator import GoogleHomeDataUpdateCoordinator
from custom_components.google_home.firmware import (
    extract_firmware_versions,
    firmware_version_family,
)
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.update import GoogleHomeUpdateEntity

CAST_VERSION = "3.80.546557"
SYSTEM_VERSION = "31.20260429.103.8712900"


@pytest.mark.parametrize("location", ["build_info", "device_info", None])
def test_display_prefers_system_firmware_in_each_response_location(location):
    """Both components are reported, but Google's display catalog uses system firmware."""
    fields = {
        "cast_build_revision": CAST_VERSION,
        "system_build_number": SYSTEM_VERSION,
    }
    payload = {location: fields} if location else fields
    assert extract_firmware_versions(payload) == (
        SYSTEM_VERSION,
        CAST_VERSION,
        SYSTEM_VERSION,
    )


def test_display_system_firmware_wins_across_response_blocks():
    """A Cast version in build_info must not mask a system version elsewhere."""
    assert extract_firmware_versions(
        {
            "build_info": {"cast_build_revision": CAST_VERSION},
            "device_info": {"system_build_number": SYSTEM_VERSION},
        }
    ) == (SYSTEM_VERSION, CAST_VERSION, SYSTEM_VERSION)


def test_speaker_keeps_cast_version_despite_numeric_system_build():
    """Speaker system build counters are not the firmware published by Google."""
    assert extract_firmware_versions(
        {
            "build_info": {
                "cast_build_revision": CAST_VERSION,
                "system_build_number": 546557,
            }
        }
    ) == (CAST_VERSION, CAST_VERSION, "546557")


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"build_info": {"build_version": CAST_VERSION}}, CAST_VERSION),
        ({"cast_build_revision": CAST_VERSION}, CAST_VERSION),
        ({"build_info": {"system_build_number": SYSTEM_VERSION}}, SYSTEM_VERSION),
        ({"version": CAST_VERSION}, CAST_VERSION),
        ({"version": 12}, None),
        ({"build_info": "unexpected", "device_info": None}, None),
        ({}, None),
    ],
)
def test_firmware_fallbacks(payload, expected):
    """Retain speaker/legacy fallbacks and ignore Eureka API schema numbers."""
    assert extract_firmware_versions(payload)[0] == expected


@pytest.mark.parametrize(
    "version, family",
    [
        (CAST_VERSION, "cast"),
        (SYSTEM_VERSION, "system"),
        ("1.68.cast_20251119_1643_RC14.834495410", None),
        ("546557", None),
        ("31.2026.103.8712900", None),
        (None, None),
    ],
)
def test_firmware_component_families(version, family):
    """Only recognize versions that are comparable to Google's catalog."""
    assert firmware_version_family(version) == family


@pytest.mark.parametrize(
    "installed, latest, expected",
    [
        (CAST_VERSION, SYSTEM_VERSION, CAST_VERSION),
        (SYSTEM_VERSION, CAST_VERSION, SYSTEM_VERSION),
        (SYSTEM_VERSION, SYSTEM_VERSION, SYSTEM_VERSION),
        ("30.20260121.103.1604600", SYSTEM_VERSION, SYSTEM_VERSION),
        ("3.78.540761", CAST_VERSION, CAST_VERSION),
        (None, SYSTEM_VERSION, None),
    ],
)
def test_catalog_only_compares_same_firmware_component(installed, latest, expected):
    """Missing system data cannot produce a false display firmware update."""
    device = GoogleHomeDevice(
        "hub", "Kitchen display", None, hardware="Google Nest Hub"
    )
    device.firmware_version = installed
    device.latest_firmware_version = "stale-catalog-version"
    coordinator = object.__new__(GoogleHomeDataUpdateCoordinator)
    coordinator._apply_firmware_to_device(
        device,
        {
            "Google Nest Hub": {"firmware_version": latest},
        },
    )
    assert device.latest_firmware_version == expected


@pytest.mark.asyncio
async def test_display_poll_reports_system_version_and_preserves_cast_diagnostic():
    """Exercise local polling through the update entity using the reported version pair."""
    device = GoogleHomeDevice(
        "hub", "Kitchen display", "synthetic-token", "192.0.2.10", "Google Nest Hub"
    )
    client = object.__new__(GlocaltokensApiClient)
    for name in (
        "get_alarms_and_timers",
        "get_alarm_volume",
        "get_current_device_volume",
        "get_do_not_disturb",
        "get_night_mode_settings",
        "get_bluetooth_status",
    ):
        setattr(client, name, AsyncMock(return_value={}))
    client.get_eureka_info = AsyncMock(
        return_value={
            "build_info": {
                "cast_build_revision": CAST_VERSION,
                "system_build_number": SYSTEM_VERSION,
            }
        }
    )

    await client.update_device_data(device)
    assert device.available
    assert device.firmware_version == SYSTEM_VERSION
    coordinator = object.__new__(GoogleHomeDataUpdateCoordinator)
    coordinator._apply_firmware_to_device(
        device,
        {
            "Google Nest Hub": {"firmware_version": SYSTEM_VERSION},
        },
    )
    entity_coordinator = MagicMock()
    entity_coordinator.get_device.return_value = device
    entity = GoogleHomeUpdateEntity(entity_coordinator, device.device_id, device.name)
    assert entity.installed_version == SYSTEM_VERSION
    assert entity.latest_version == SYSTEM_VERSION
    assert entity.extra_state_attributes["cast_firmware_version"] == CAST_VERSION
    assert entity.extra_state_attributes["system_firmware_version"] == SYSTEM_VERSION
    assert entity.state == "off"
