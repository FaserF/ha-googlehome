"""Exceptions for Google Home integration."""

from homeassistant.exceptions import HomeAssistantError


class GoogleHomeException(HomeAssistantError):
    """Base Google Home exception."""


class InvalidMasterToken(GoogleHomeException):
    """Exception when the master token is invalid."""


class AuthenticationFailed(GoogleHomeException):
    """Exception when authentication fails."""


class TwoFactorRequired(AuthenticationFailed):
    """Exception when Google 2FA or App Password is required."""


class AdvancedProtectionActive(AuthenticationFailed):
    """Exception when Google Advanced Protection Program blocks password/app password login."""


class DeviceConnectionError(GoogleHomeException):
    """Exception when connection to Google Home device fails."""
