"""Test light platform."""

from unittest.mock import MagicMock

from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.core import HomeAssistant

from custom_components.google_home.light import GoogleHomeCloudLight


async def test_find_target_media_player(hass: HomeAssistant) -> None:
    """Test finding a target media player strictly checks for PLAY_MEDIA support."""
    coordinator_mock = MagicMock()
    coordinator_mock.data = [
        MagicMock(
            device_id="test_device", traits=[], hardware_model="", name="My Speaker"
        )
    ]
    light = GoogleHomeCloudLight(
        coordinator=coordinator_mock,
        device_id="test_device",
    )
    light.hass = hass
    device_mock = MagicMock()
    device_mock.name = "My Speaker"
    light.get_device = MagicMock(return_value=device_mock)

    # Add a mock state that matches name but doesn't support PLAY_MEDIA
    hass.states.async_set(
        "media_player.my_speaker",
        "idle",
        {
            "friendly_name": "My Speaker",
            "supported_features": MediaPlayerEntityFeature.TURN_ON,
        },
    )

    target = light._find_target_media_player()
    assert target is None

    # Update state to support PLAY_MEDIA
    hass.states.async_set(
        "media_player.my_speaker",
        "idle",
        {
            "friendly_name": "My Speaker",
            "supported_features": MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.TURN_ON,
        },
    )

    target = light._find_target_media_player()
    assert target == "media_player.my_speaker"
