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
    structure_id: str | None = None
    structure_name: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    is_home_assistant_synced: bool = False
    traits: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    online: bool = True

    @property
    def manufacturer(self) -> str:
        """Return the device manufacturer / service provider."""
        hw = (self.hardware_model or "").lower()
        hw_v = (self.hardware_version or "").lower()
        nm = (self.name or "").lower()
        combined = f"{hw} {hw_v} {nm}"

        if "lenovo" in combined or "cd-" in combined:
            return "Lenovo"
        if "lg" in combined or "wk7" in combined or "thinq" in combined:
            return "LG Electronics"
        if "jbl" in combined or "link" in combined:
            return "JBL"
        if "sony" in combined or "lf-" in combined:
            return "Sony"
        if "bose" in combined:
            return "Bose"
        if "harman" in combined or "kardon" in combined:
            return "Harman Kardon"
        if "marshall" in combined:
            return "Marshall"
        if "panasonic" in combined:
            return "Panasonic"
        if "sonos" in combined:
            return "Sonos"
        if (
            "xiaomi" in combined
            or "roborock" in combined
            or "dreame" in combined
            or "yeelink" in combined
        ):
            return "Xiaomi"
        if "philips" in combined or "hue" in combined:
            return "Philips Hue"
        if "tuya" in combined or "smart life" in combined:
            return "Smart Life"
        if "tado" in combined:
            return "tado°"
        if "nuki" in combined:
            return "Nuki"
        if "ring" in combined:
            return "Ring"
        if "nest" in combined:
            return "Google Nest"

        # Check agent_name / agent_id if valid and not generic "assistant"
        raw_agent = (self.agent_name or self.agent_id or "").strip()
        if raw_agent and raw_agent.lower() not in (
            "assistant",
            "google_assistant",
            "google assistant",
            "googlehome",
            "google_home",
            "cast",
        ):
            return raw_agent

        return "Google"

    @property
    def model_name(self) -> str:
        """Return the hardware model or user-friendly device type name."""
        if self.hardware_model and self.hardware_model.strip():
            return self.hardware_model.strip()
        if self.hardware_version and self.hardware_version.strip():
            return self.hardware_version.strip()
        if self.device_type:
            # action.devices.types.LIGHT -> Light, action.devices.types.FAN -> Fan
            parts = self.device_type.split(".")
            raw_type = parts[-1].replace("_", " ").title()
            return f"{self.manufacturer} {raw_type}".strip()
        return "Google Cloud Device"

    @property
    def is_light(self) -> bool:
        """Return True if device acts as a light."""
        if (
            self.is_automation_routine
            or "action.devices.types.SPEAKER" in self.device_type
        ):
            return False
        return (
            "action.devices.types.LIGHT" in self.device_type
            or "action.devices.traits.ColorSetting" in self.traits
            or (
                "action.devices.traits.Brightness" in self.traits
                and "action.devices.traits.ScreenBrightness" not in self.traits
            )
        )

    @property
    def is_fan(self) -> bool:
        """Return True if device acts as a fan or air purifier."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.FAN" in self.device_type
            or "action.devices.types.AIRPURIFIER" in self.device_type
            or "action.devices.traits.FanSpeed" in self.traits
        )

    @property
    def is_media_player(self) -> bool:
        """Return True if device is a TV, Speaker, Soundbar, Receiver or Streaming Device."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.TV" in self.device_type
            or "action.devices.types.SPEAKER" in self.device_type
            or "action.devices.types.SOUNDBAR" in self.device_type
            or "action.devices.types.AUDIO_VIDEO_RECEIVER" in self.device_type
            or "action.devices.types.SETTOP" in self.device_type
            or "action.devices.types.STREAMING_BOX" in self.device_type
            or "action.devices.types.STREAMING_STICK" in self.device_type
            or "action.devices.types.STREAMING_SOUNDBAR" in self.device_type
            or "action.devices.traits.MediaState" in self.traits
            or "action.devices.traits.TransportControl" in self.traits
            or "action.devices.traits.AppSelector" in self.traits
            or "action.devices.traits.InputSelector" in self.traits
        )

    @property
    def is_humidifier(self) -> bool:
        """Return True if device is a humidifier or dehumidifier."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.HUMIDIFIER" in self.device_type
            or "action.devices.types.DEHUMIDIFIER" in self.device_type
            or "action.devices.traits.HumiditySetting" in self.traits
        )

    @property
    def is_valve(self) -> bool:
        """Return True if device is a valve, faucet, or sprinkler."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.VALVE" in self.device_type
            or "action.devices.types.SPRINKLER" in self.device_type
            or "action.devices.types.FAUCET" in self.device_type
        )

    @property
    def is_control_bridge(self) -> bool:
        """Return True if device is a control bridge / hub (e.g. Philips Hue Bridge, Matter Bridge)."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.CONTROL_BRIDGE" in self.device_type
            or "action.devices.types.HUB" in self.device_type
            or "bridge" in self.device_type.lower()
        )

    @property
    def is_switch(self) -> bool:
        """Return True if device acts as a switch or outlet."""
        if self.is_automation_routine or self.is_control_bridge:
            return False
        return (
            "action.devices.types.SWITCH" in self.device_type
            or "action.devices.types.OUTLET" in self.device_type
            or "action.devices.types.PLUG" in self.device_type
            or "action.devices.types.FRYER" in self.device_type
            or (
                "action.devices.traits.OnOff" in self.traits
                and not self.is_light
                and not self.is_fan
                and not self.is_media_player
                and not self.is_humidifier
                and not self.is_valve
                and not self.is_vacuum
                and not self.is_lock
                and not self.is_cover
                and not self.is_climate
                and not self.is_security_system
                and not self.is_binary_sensor
            )
        )

    @property
    def is_camera(self) -> bool:
        """Return True if device is a camera or doorbell."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.CAMERA" in self.device_type
            or "action.devices.types.DOORBELL" in self.device_type
            or "action.devices.traits.CameraStream" in self.traits
            or "nest_cam" in (self.hardware_model or "").lower()
        )

    @property
    def is_vacuum(self) -> bool:
        """Return True if device is a robotic vacuum cleaner or mower."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.VACUUM" in self.device_type
            or "action.devices.types.MOWER" in self.device_type
            or (
                "action.devices.traits.StartStop" in self.traits
                and "action.devices.traits.Dock" in self.traits
            )
        )

    @property
    def is_climate(self) -> bool:
        """Return True if device is a thermostat, AC, or heater."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.THERMOSTAT" in self.device_type
            or "action.devices.types.AC_UNIT" in self.device_type
            or "action.devices.types.HEATER" in self.device_type
            or "action.devices.types.AIRCOOLER" in self.device_type
            or "action.devices.traits.TemperatureSetting" in self.traits
        )

    @property
    def is_lock(self) -> bool:
        """Return True if device is a smart lock."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.LOCK" in self.device_type
            or "action.devices.traits.LockUnlock" in self.traits
        )

    @property
    def is_cover(self) -> bool:
        """Return True if device is a cover, blind, curtain, garage, or door."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.BLINDS" in self.device_type
            or "action.devices.types.CURTAIN" in self.device_type
            or "action.devices.types.SHUTTER" in self.device_type
            or "action.devices.types.GARAGE" in self.device_type
            or "action.devices.types.DOOR" in self.device_type
            or "action.devices.types.AWNING" in self.device_type
            or "action.devices.traits.OpenClose" in self.traits
        )

    @property
    def is_security_system(self) -> bool:
        """Return True if device is a security system / alarm."""
        if self.is_automation_routine:
            return False
        return (
            "action.devices.types.SECURITY_SYSTEM" in self.device_type
            or "action.devices.traits.ArmDisarm" in self.traits
            or "nest_secure" in (self.hardware_model or "").lower()
        )

    @property
    def is_binary_sensor(self) -> bool:
        """Return True if device is a sensor (contact, motion, occupancy, smoke, leak)."""
        if self.is_automation_routine:
            return False
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
        )
