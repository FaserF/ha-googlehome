"""Test assistant_helper command formatting."""

import unittest.mock

from custom_components.google_home.assistant_helper import format_command


def test_format_command_en():
    """Test English command formatting."""
    hass = unittest.mock.MagicMock()
    hass.config.language = "en"

    cmd = format_command(hass, "turn_on", "Living Room Light")
    assert cmd == "Turn on Living Room Light"

    cmd_bright = format_command(
        hass, "set_brightness", "Living Room Light", brightness=50
    )
    assert cmd_bright == "Set brightness on Living Room Light to 50%"


def test_format_command_de():
    """Test German command formatting."""
    hass = unittest.mock.MagicMock()
    hass.config.language = "de"

    cmd = format_command(hass, "turn_on", "Wohnzimmerlampe")
    assert cmd == "Schalte Wohnzimmerlampe ein"

    cmd_temp = format_command(hass, "set_temperature", "Thermostat", temperature=21.5)
    assert cmd_temp == "Setze die Temperatur von Thermostat auf 21.5 Grad"


def test_format_command_fallback():
    """Test fallback when language is not recognized."""
    hass = unittest.mock.MagicMock()
    hass.config.language = "fr"

    cmd = format_command(hass, "turn_off", "Kitchen Light")
    assert cmd == "Turn off Kitchen Light"
