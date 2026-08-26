"""Test config flow constants and structure."""

from custom_components.google_home.const import (
    AUTH_METHOD_CREDENTIALS,
    AUTH_METHOD_TOKEN,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


def test_constants():
    """Test basic constants."""
    assert DOMAIN == "google_home"
    assert AUTH_METHOD_TOKEN == "token"
    assert AUTH_METHOD_CREDENTIALS == "credentials"
    assert DEFAULT_UPDATE_INTERVAL == 60
