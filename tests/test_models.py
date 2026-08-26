"""Test Google Home models."""

from custom_components.google_home.models import (
    GoogleHomeAlarm,
    GoogleHomeAlarmStatus,
    GoogleHomeDevice,
    GoogleHomeTimer,
    GoogleHomeTimerStatus,
    convert_from_ms_to_s,
)


def test_convert_from_ms_to_s():
    """Test milliseconds to seconds conversion."""
    assert convert_from_ms_to_s(1000) == 1
    assert convert_from_ms_to_s(1500) == 2
    assert convert_from_ms_to_s(0) == 0


def test_google_home_device_creation():
    """Test creating a device."""
    dev = GoogleHomeDevice(
        device_id="dev123",
        name="Living Room Speaker",
        auth_token="token_abc",
        ip_address="192.168.1.50",
        hardware="Google Nest Audio",
    )
    assert dev.device_id == "dev123"
    assert dev.name == "Living Room Speaker"
    assert dev.auth_token == "token_abc"
    assert dev.ip_address == "192.168.1.50"
    assert dev.hardware == "Google Nest Audio"
    assert dev.available is True

    dev.set_do_not_disturb(True)
    assert dev.get_do_not_disturb() is True

    dev.set_wifi_info("MyHomeWiFi", -60)
    assert dev.get_wifi_ssid() == "MyHomeWiFi"
    assert dev.get_wifi_rssi() == -60

    dev.set_bluetooth_mac("AA:BB:CC:DD:EE:FF")
    assert dev.get_bluetooth_mac() == "AA:BB:CC:DD:EE:FF"

    dev.set_alarm_volume(75)
    assert dev.get_alarm_volume() == 75.0

    dev.set_device_volume(60)
    assert dev.get_device_volume() == 60.0

    dev.set_system_info(firmware="1.56.281627", mac="00:1A:2B:3C:4D:5E")
    assert dev.firmware_version == "1.56.281627"
    assert dev.mac_address == "00:1A:2B:3C:4D:5E"


def test_google_home_timer_parsing():
    """Test parsing timers."""
    timer = GoogleHomeTimer(
        timer_id="timer/test_123",
        fire_time=1700000000000,
        duration=300000,
        status=1,
        label="Pizza",
    )
    assert timer.timer_id == "timer/test_123"
    assert timer.status == GoogleHomeTimerStatus.SET
    assert timer.label == "Pizza"
    assert timer.fire_time == 1700000000
    assert timer.date_time is not None
    assert timer.date_time.tzinfo is not None

    data = timer.as_dict()
    assert data["timer_id"] == "timer/test_123"
    assert data["status"] == "set"
    assert data["label"] == "Pizza"


def test_google_home_alarm_parsing():
    """Test parsing alarms."""
    alarm = GoogleHomeAlarm(
        alarm_id="alarm/test_456",
        fire_time=1700000000000,
        status=1,
        label="Wakeup",
        recurrence="[1,2,3,4,5]",
    )
    assert alarm.alarm_id == "alarm/test_456"
    assert alarm.status == GoogleHomeAlarmStatus.SET
    assert alarm.label == "Wakeup"
    assert alarm.recurrence == "[1,2,3,4,5]"
    assert alarm.fire_time == 1700000000
    assert alarm.date_time is not None
    assert alarm.date_time.tzinfo is not None

    data = alarm.as_dict()
    assert data["alarm_id"] == "alarm/test_456"
    assert data["status"] == "set"
    assert data["label"] == "Wakeup"
    assert data["recurrence"] == "[1,2,3,4,5]"


def test_device_alarms_and_timers_sorting():
    """Test device sorting logic for alarms and timers."""
    dev = GoogleHomeDevice(
        device_id="dev123",
        name="Test",
        auth_token="token",
    )

    dev.set_timers(
        [
            {
                "id": "timer/2",
                "fire_time": 2000000000000,
                "original_duration": 100000,
                "status": 1,
                "label": "Second",
            },
            {
                "id": "timer/1",
                "fire_time": 1000000000000,
                "original_duration": 50000,
                "status": 1,
                "label": "First",
            },
        ]
    )

    next_timer = dev.get_next_timer()
    assert next_timer is not None
    assert next_timer.timer_id == "timer/1"

    dev.set_alarms(
        [
            {
                "id": "alarm/inactive",
                "fire_time": 500000000000,
                "status": 4,  # INACTIVE
                "label": "Inactive",
                "recurrence": None,
            },
            {
                "id": "alarm/active",
                "fire_time": 1500000000000,
                "status": 1,  # SET
                "label": "Active",
                "recurrence": None,
            },
        ]
    )

    next_alarm = dev.get_next_alarm()
    assert next_alarm is not None
    assert next_alarm.alarm_id == "alarm/active"
