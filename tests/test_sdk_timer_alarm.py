"""Test timer number and alarm time entities for Google Assistant SDK execution."""

from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import GoogleHomeSetTimerNumber
from custom_components.google_home.time import GoogleHomeSetAlarmTime


@pytest.mark.asyncio
async def test_set_timer_number_sends_target_command():
    """Test that GoogleHomeSetTimerNumber formats command and dispatches to Assistant SDK targeted at the device."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.services = MagicMock()
    hass.services.has_service.return_value = True
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()

    # Mock media_player state for targeting
    mp_state = MagicMock()
    mp_state.entity_id = "media_player.kitchen_speaker"
    mp_state.attributes = {"friendly_name": "Kitchen Speaker"}
    hass.states.async_all.return_value = [mp_state]

    coordinator = MagicMock()
    coordinator.data = []

    device_id = "device_123"
    device_name = "Kitchen Speaker"

    timer_entity = GoogleHomeSetTimerNumber(
        coordinator=coordinator,
        device_id=device_id,
        device_name=device_name,
    )
    timer_entity.hass = hass
    timer_entity.async_write_ha_state = MagicMock()

    assert timer_entity.label == "set_timer"
    assert timer_entity.unique_id == f"{device_id}_set_timer"

    await timer_entity.async_set_native_value(15.0)

    assert timer_entity.native_value == 15.0
    hass.services.async_call.assert_called_once()
    domain, service, service_data = hass.services.async_call.call_args[0]
    assert domain == "google_assistant_sdk"
    assert service == "send_text_command"
    assert "15" in service_data["command"]
    assert service_data["media_player"] == "media_player.kitchen_speaker"


@pytest.mark.asyncio
async def test_set_alarm_time_sends_target_command():
    """Test that GoogleHomeSetAlarmTime formats command and dispatches to Assistant SDK targeted at the device."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.services = MagicMock()
    hass.services.has_service.return_value = True
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()

    mp_state = MagicMock()
    mp_state.entity_id = "media_player.bedroom_speaker"
    mp_state.attributes = {"friendly_name": "Bedroom Speaker"}
    hass.states.async_all.return_value = [mp_state]

    coordinator = MagicMock()
    coordinator.data = []

    device_id = "device_456"
    device_name = "Bedroom Speaker"

    alarm_entity = GoogleHomeSetAlarmTime(
        coordinator=coordinator,
        device_id=device_id,
        device_name=device_name,
    )
    alarm_entity.hass = hass
    alarm_entity.async_write_ha_state = MagicMock()

    assert alarm_entity.label == "set_alarm"
    assert alarm_entity.unique_id == f"{device_id}_set_alarm"

    target_time = time(7, 30)
    await alarm_entity.async_set_value(target_time)

    assert alarm_entity.native_value == target_time
    hass.services.async_call.assert_called_once()
    domain, service, service_data = hass.services.async_call.call_args[0]
    assert domain == "google_assistant_sdk"
    assert service == "send_text_command"
    assert "07:30" in service_data["command"]
    assert service_data["media_player"] == "media_player.bedroom_speaker"
