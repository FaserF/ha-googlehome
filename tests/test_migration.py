"""Test migration entry logic."""

from unittest.mock import MagicMock

import pytest

from custom_components.google_home import async_migrate_entry
from custom_components.google_home.const import (
    AUTH_METHOD_APP_PASSWORD,
    AUTH_METHOD_TOKEN,
    CONF_ANDROID_ID,
    CONF_AUTH_METHOD,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    MODE_LOCAL,
)


@pytest.mark.asyncio
async def test_migration_from_leikoilja_with_master_token():
    """Test migration from leikoilja integration entry when master_token exists."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()

    entry = MagicMock()
    entry.version = 1
    entry.unique_id = "old_unique_id"
    entry.data = {
        CONF_USERNAME: "test@gmail.com",
        CONF_PASSWORD: "secret_password",
        CONF_MASTER_TOKEN: "aas_et/example_token",
        CONF_ANDROID_ID: "android_12345",
        CONF_UPDATE_INTERVAL: 180,
    }

    result = await async_migrate_entry(hass, entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_called_once()
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["version"] == 3
    assert kwargs["unique_id"] == "test@gmail.com"
    assert kwargs["title"] == "Google Home (test@gmail.com)"

    migrated_data = kwargs["data"]
    assert migrated_data[CONF_AUTH_METHOD] == AUTH_METHOD_TOKEN
    assert migrated_data[CONF_USERNAME] == "test@gmail.com"
    assert migrated_data[CONF_PASSWORD] == "secret_password"
    assert migrated_data[CONF_MASTER_TOKEN] == "aas_et/example_token"
    assert migrated_data[CONF_ANDROID_ID] == "android_12345"
    assert migrated_data[CONF_LOCAL_UPDATE_INTERVAL] == 180
    assert migrated_data[CONF_OPERATION_MODE] == MODE_LOCAL


@pytest.mark.asyncio
async def test_migration_from_leikoilja_without_master_token():
    """Test migration from leikoilja integration entry when only legacy credentials exist."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()

    entry = MagicMock()
    entry.version = 1
    entry.unique_id = None
    entry.data = {
        CONF_USERNAME: "user@domain.com",
        CONF_PASSWORD: "my_password",
        CONF_ANDROID_ID: "android_999",
    }

    result = await async_migrate_entry(hass, entry)

    assert result is True
    hass.config_entries.async_update_entry.assert_called_once()
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["version"] == 3
    assert kwargs["unique_id"] == "user@domain.com"

    migrated_data = kwargs["data"]
    assert migrated_data[CONF_AUTH_METHOD] == AUTH_METHOD_APP_PASSWORD
    assert migrated_data[CONF_USERNAME] == "user@domain.com"
    assert migrated_data[CONF_PASSWORD] == "my_password"
    assert migrated_data[CONF_LOCAL_UPDATE_INTERVAL] == 120
    assert migrated_data[CONF_OPERATION_MODE] == MODE_LOCAL
