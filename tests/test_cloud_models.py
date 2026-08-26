"""Test Google Home Cloud models and trait classification."""

from custom_components.google_home.cloud_models import CloudHomeDevice


def test_cloud_device_light_classification():
    """Test classification of light devices."""
    light = CloudHomeDevice(
        device_id="light_1",
        name="Living Room Ceiling Light",
        device_type="action.devices.types.LIGHT",
        traits=["action.devices.traits.OnOff", "action.devices.traits.Brightness"],
    )
    assert light.is_light is True
    assert light.is_switch is False
    assert light.is_vacuum is False
    assert light.is_climate is False


def test_cloud_device_switch_classification():
    """Test classification of switch and plug devices."""
    plug = CloudHomeDevice(
        device_id="plug_1",
        name="Coffee Maker",
        device_type="action.devices.types.OUTLET",
        traits=["action.devices.traits.OnOff"],
    )
    assert plug.is_switch is True
    assert plug.is_light is False


def test_cloud_device_vacuum_classification():
    """Test classification of vacuum cleaners."""
    vacuum = CloudHomeDevice(
        device_id="vac_1",
        name="Roborock S7",
        device_type="action.devices.types.VACUUM",
        traits=["action.devices.traits.StartStop", "action.devices.traits.Dock"],
    )
    assert vacuum.is_vacuum is True
    assert vacuum.is_switch is False


def test_cloud_device_climate_classification():
    """Test classification of thermostats and AC units."""
    thermostat = CloudHomeDevice(
        device_id="nest_tstat",
        name="Hallway Thermostat",
        device_type="action.devices.types.THERMOSTAT",
        traits=["action.devices.traits.TemperatureSetting"],
    )
    assert thermostat.is_climate is True


def test_cloud_device_lock_classification():
    """Test classification of smart locks."""
    lock = CloudHomeDevice(
        device_id="front_door_lock",
        name="Front Door Lock",
        device_type="action.devices.types.LOCK",
        traits=["action.devices.traits.LockUnlock"],
    )
    assert lock.is_lock is True


def test_cloud_device_cover_classification():
    """Test classification of covers, blinds, and shutters."""
    blinds = CloudHomeDevice(
        device_id="bedroom_blinds",
        name="Bedroom Blinds",
        device_type="action.devices.types.BLINDS",
        traits=["action.devices.traits.OpenClose"],
    )
    assert blinds.is_cover is True


def test_cloud_device_security_system():
    """Test classification of security systems."""
    alarm = CloudHomeDevice(
        device_id="nest_guard",
        name="Nest Secure",
        device_type="action.devices.types.SECURITY_SYSTEM",
        traits=["action.devices.traits.ArmDisarm"],
    )
    assert alarm.is_security_system is True


def test_cloud_device_camera():
    """Test classification of cameras and doorbells."""
    cam = CloudHomeDevice(
        device_id="nest_cam_outdoor",
        name="Backyard Camera",
        device_type="action.devices.types.CAMERA",
        traits=["action.devices.traits.CameraStream"],
    )
    assert cam.is_camera is True


def test_cloud_device_binary_sensor():
    """Test classification of sensors."""
    motion = CloudHomeDevice(
        device_id="hallway_motion",
        name="Hallway Motion",
        device_type="action.devices.types.SENSOR",
        traits=["action.devices.traits.OccupancySensing"],
    )
    assert motion.is_binary_sensor is True


def test_cloud_device_automation_routine():
    """Test classification of Google Home automations and routines."""
    routine = CloudHomeDevice(
        device_id="routine_good_morning",
        name="Guten Morgen Ablauf",
        device_type="action.devices.types.SCENE",
        traits=["action.devices.traits.Scene"],
    )
    assert routine.is_automation_routine is True
