"""Exercise setup modes and repair failures through platform forwarding."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.google_home import async_setup_entry
from custom_components.google_home.const import (
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    DATA_CLOUD_COORDINATOR,
    DOMAIN,
    MODE_HYBRID,
    MODE_LOCAL,
    PLATFORMS,
)


@pytest.fixture
def local_setup(hass: HomeAssistant):
    """Mock transport/coordinators while preserving real entry and HA lifecycle."""
    coordinator = MagicMock(data=[])
    coordinator.async_config_entry_first_refresh = AsyncMock()
    with (
        patch("custom_components.google_home.async_get_clientsession"),
        patch(
            "custom_components.google_home.zeroconf.async_get_instance",
            new_callable=AsyncMock,
        ),
        patch("custom_components.google_home.GlocaltokensApiClient"),
        patch(
            "custom_components.google_home.GoogleHomeDataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch(
            "custom_components.google_home.cloud_api.GoogleHomeCloudClient"
        ) as cloud_client,
        patch(
            "custom_components.google_home._async_cleanup_stale_devices_and_entities",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.google_home.async_repair_placeholder_macs",
            new_callable=AsyncMock,
        ) as repair,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ) as forward,
    ):
        yield repair, forward, cloud_client


def add_entry(hass: HomeAssistant, mode: str, token: str | None = None):
    data = {CONF_OPERATION_MODE: mode}
    if token is not None:
        data[CONF_MASTER_TOKEN] = token
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    return entry


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode, token",
    [(MODE_LOCAL, None), (MODE_LOCAL, "synthetic"), (MODE_HYBRID, None)],
)
async def test_setup_without_cloud_coordinator(hass, local_setup, mode, token):
    """Skipping cloud setup must still repair the registry and load platforms."""
    repair, forward, cloud_client = local_setup
    entry = add_entry(hass, mode, token)
    assert await async_setup_entry(hass, entry)
    cloud_client.assert_not_called()
    assert DATA_CLOUD_COORDINATOR not in hass.data[DOMAIN][entry.entry_id]
    repair.assert_awaited_once_with(hass, entry, [])
    forward.assert_awaited_once_with(entry, PLATFORMS)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [OSError("Synthetic backup failure"), ValueError("Synthetic collision")]
)
async def test_repair_failure_logs_traceback_and_loads_platforms(
    hass, local_setup, caplog, error
):
    """An optional repair failure must not make all device entities unavailable."""
    repair, forward, _ = local_setup
    repair.side_effect = error
    entry = add_entry(hass, MODE_LOCAL)
    with caplog.at_level(logging.ERROR, logger="custom_components.google_home"):
        assert await async_setup_entry(hass, entry)
    forward.assert_awaited_once_with(entry, PLATFORMS)
    record = next(
        record
        for record in caplog.records
        if "registry repair failed" in record.message
    )
    assert record.exc_info[1] is error


@pytest.mark.asyncio
async def test_setup_cancellation_is_not_swallowed(hass, local_setup):
    repair, forward, _ = local_setup
    repair.side_effect = asyncio.CancelledError
    entry = add_entry(hass, MODE_LOCAL)
    with pytest.raises(asyncio.CancelledError):
        await async_setup_entry(hass, entry)
    forward.assert_not_awaited()
