"""Cloud HomeGraph device model for Google Home."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CloudHomeDevice:
    """Representation of a Google Home Cloud (HomeGraph) Device."""

    device_id: str
    name: str
    device_type: str
    hardware_model: str | None = None
    hardware_version: str | None = None
    firmware_version: str | None = None
    mac_address: str | None = None
    room_name: str | None = None
    structure_name: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    is_home_assistant_synced: bool = False
    traits: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    online: bool = True

    @property
    def is_light(self) -> bool:
        """Return True if device acts as a light."""
        return (
            "action.devices.types.LIGHT" in self.device_type
            or "action.devices.traits.Brightness" in self.traits
            or "action.devices.traits.ColorSetting" in self.traits
            or (
                "action.devices.traits.OnOff" in self.traits
                and "light" in self.name.lower()
            )
        )

    @property
    def is_switch(self) -> bool:
        """Return True if device acts as a switch or outlet."""
        return (
            "action.devices.types.SWITCH" in self.device_type
            or "action.devices.types.OUTLET" in self.device_type
            or (
                "action.devices.traits.OnOff" in self.traits
                and not self.is_light
                and not self.is_vacuum
                and not self.is_lock
                and not self.is_cover
            )
        )

    @property
    def is_camera(self) -> bool:
        """Return True if device is a camera or doorbell."""
        return (
            "action.devices.types.CAMERA" in self.device_type
            or "action.devices.types.DOORBELL" in self.device_type
            or "action.devices.traits.CameraStream" in self.traits
            or "nest_cam" in (self.hardware_model or "").lower()
        )

    @property
    def is_vacuum(self) -> bool:
        """Return True if device is a robotic vacuum cleaner."""
        return (
            "action.devices.types.VACUUM" in self.device_type
            or "action.devices.traits.StartStop" in self.traits
            and "action.devices.traits.Dock" in self.traits
            or "vacuum" in self.name.lower()
            or "sauger" in self.name.lower()
        )

    @property
    def is_climate(self) -> bool:
        """Return True if device is a thermostat or AC."""
        return (
            "action.devices.types.THERMOSTAT" in self.device_type
            or "action.devices.types.AC_UNIT" in self.device_type
            or "action.devices.types.HEATER" in self.device_type
            or "action.devices.traits.TemperatureSetting" in self.traits
        )

    @property
    def is_lock(self) -> bool:
        """Return True if device is a smart lock."""
        return (
            "action.devices.types.LOCK" in self.device_type
            or "action.devices.traits.LockUnlock" in self.traits
            or "schloss" in self.name.lower()
            or "lock" in self.name.lower()
        )

    @property
    def is_cover(self) -> bool:
        """Return True if device is a cover, blind, curtain, garage, or door."""
        return (
            "action.devices.types.BLINDS" in self.device_type
            or "action.devices.types.CURTAIN" in self.device_type
            or "action.devices.types.SHUTTER" in self.device_type
            or "action.devices.types.GARAGE" in self.device_type
            or "action.devices.types.DOOR" in self.device_type
            or "action.devices.traits.OpenClose" in self.traits
        )

    @property
    def is_security_system(self) -> bool:
        """Return True if device is a security system / alarm."""
        return (
            "action.devices.types.SECURITY_SYSTEM" in self.device_type
            or "action.devices.traits.ArmDisarm" in self.traits
            or "nest_secure" in (self.hardware_model or "").lower()
        )

    @property
    def is_binary_sensor(self) -> bool:
        """Return True if device is a sensor (contact, motion, occupancy, smoke, leak)."""
        return (
            "action.devices.types.SENSOR" in self.device_type
            or "action.devices.types.DOORBELL" in self.device_type
            or "action.devices.traits.SensorState" in self.traits
            or "action.devices.traits.OccupancySensing" in self.traits
        )

    @property
    def is_automation_routine(self) -> bool:
        """Return True if device is a Google Home Automation or Routine Scene."""
        return (
            "action.devices.types.SCENE" in self.device_type
            or "action.devices.types.ROUTINE" in self.device_type
            or "action.devices.traits.Scene" in self.traits
            or "action.devices.traits.Modes" in self.traits
            and "routine" in self.name.lower()
        )
