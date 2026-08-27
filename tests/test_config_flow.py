"""Test config flow constants and structure."""

from custom_components.google_home.const import (
    ADDON_CONTAINER_HOSTS,
    AUTH_METHOD_ADDON,
    AUTH_METHOD_CREDENTIALS,
    AUTH_METHOD_TOKEN,
    DEFAULT_ADDON_HOST,
    DEFAULT_ADDON_PORT,
    DEFAULT_LOCAL_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


def test_constants():
    """Test basic constants."""
    assert DOMAIN == "google_home"
    assert AUTH_METHOD_TOKEN == "token"
    assert AUTH_METHOD_ADDON == "addon"
    assert AUTH_METHOD_CREDENTIALS == "credentials"
    assert DEFAULT_UPDATE_INTERVAL == 120
    assert DEFAULT_LOCAL_UPDATE_INTERVAL == 120
    assert DEFAULT_ADDON_HOST == "605cee21_googlehome"
    assert DEFAULT_ADDON_PORT == 8195
    assert "605cee21_googlehome" in ADDON_CONTAINER_HOSTS
    assert "edfe50eb_googlehome" in ADDON_CONTAINER_HOSTS
    assert "127.0.0.1" in ADDON_CONTAINER_HOSTS
