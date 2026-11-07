"""Data models and evaluation functions for Bluetooth presence tracking."""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

try:
    from bluetooth_data_tools import get_cipher_for_irk, resolve_private_address
except ImportError:
    get_cipher_for_irk = None  # type: ignore[assignment]
    resolve_private_address = None  # type: ignore[assignment]

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MAC

from .const import (
    BLUETOOTH_CONFIRMATION_LEASE,
    BLUETOOTH_MAX_SCAN_GAP,
    BLUETOOTH_PRESENCE_WINDOW,
    BLUETOOTH_SCAN_INTERVAL,
    CONF_ADDITIONAL_DEPARTURE_DELAY,
    CONF_IRK,
    DEPARTURE_DELAY_VALUES,
)
from .models import GoogleHomeDevice
from .types import GoogleHomeConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)

IRK_LENGTH = 16


class TrackerState(StrEnum):
    """State of a tracked Bluetooth device."""

    HOME = "home"
    NOT_HOME = "not_home"
    # Nothing is known yet since setup
    UNKNOWN = "unknown"
    # Was known, but the speakers can't tell any more
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class TrackerUpdate:
    """State of a tracked device after an update, and the speakers that hear it."""

    state: TrackerState
    # Median RSSI in dBm of each speaker over the latest completed window, by
    # speaker name, strongest first
    speakers: dict[str, int]


def parse_irk(value: str) -> bytes | None:
    """Return the IRK in a format Home Assistant's Private BLE Device accepts.

    That is hex, or base64 as macOS Keychain shows it, which is in reverse byte
    order. Returns None for anything that isn't 16 bytes.
    """
    value = value.strip().removeprefix("irk:")
    try:
        if value.endswith("="):
            irk = base64.b64decode(value, validate=True)[::-1]
        else:
            irk = bytes.fromhex(re.sub(r"[\s:-]", "", value.removeprefix("0x")))
    except ValueError:
        return None
    return irk if len(irk) == IRK_LENGTH else None


def normalize_mac(value: str) -> str | None:
    """Return a MAC address as AA:BB:CC:DD:EE:FF, or None if it isn't one."""
    digits = re.sub(r"[\s:.-]", "", value)
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", digits):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2)).upper()


def parse_mac(value: str) -> str | None:
    """Return a MAC address written as six hex pairs, as AA:BB:CC:DD:EE:FF.

    The pairs are separated all by colons or all by hyphens. Returns None for
    anything else.
    """
    if not re.fullmatch(
        r"[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}", value
    ):
        return None
    return value.replace("-", ":").upper()


@dataclass(frozen=True)
class DepartureToken:
    """A single pending transition, not persisted absence evidence."""

    policy_generation: int
    sighted: float
    deadline: float


def configured_departure_delay(subentry: ConfigSubentry) -> int:
    """Missing or invalid legacy metadata leaves the normal timing in place."""
    value = subentry.data.get(CONF_ADDITIONAL_DEPARTURE_DELAY, 0)
    if (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and value in DEPARTURE_DELAY_VALUES
    ):
        return int(value)
    return 0


class TrackedDevice:
    """A Bluetooth device that the user tracks, identified by its IRK or MAC address."""

    def __init__(self, subentry: ConfigSubentry) -> None:
        """Create a tracked device from its subentry."""
        self.subentry_id = subentry.subentry_id
        irk: str | None = subentry.data.get(CONF_IRK)
        # The subentry flow saves the IRK as hex, in the order the cipher takes
        self._cipher = (
            get_cipher_for_irk(bytes.fromhex(irk))
            if (irk and get_cipher_for_irk is not None)
            else None
        )
        self._mac: str | None = subentry.data.get(CONF_MAC)
        self.identity = (irk, self._mac)
        self.departure_delay = configured_departure_delay(subentry)
        self.policy_generation = 0
        self.pending_departure: DepartureToken | None = None
        # Start of the latest scan that heard the device
        self.last_sighted: float | None = None
        # The latest home or away state, and when the speakers last confirmed it
        self.state = TrackerState.UNKNOWN
        self.confirmed_at: float | None = None
        self.confirmed_now = False
        self.last_sighted_utc: float | None = None
        self.live_sighting = False
        self.provenance = "live"
        # The strongest RSSI each speaker heard the device at in this update,
        # by the speaker's device ID
        self.heard: dict[str, int] = {}
        # The state of the latest update, and the window of RSSI readings by
        # device ID since it started or the last window completed
        self.shown_state: TrackerState | None = None
        self.window_start = 0.0
        self.readings: dict[str, list[int]] = {}
        self.speakers: dict[str, int] = {}

    def matches(self, address: str) -> bool:
        """Return whether a normalized address is this device's."""
        if self._cipher is not None:
            if resolve_private_address is None:
                return False
            # Returns False for addresses that aren't resolvable private ones
            return bool(resolve_private_address(self._cipher, address))
        return address == self._mac


@dataclass
class SpeakerScan:
    """Bluetooth scan state of one speaker. Times are monotonic, in seconds."""

    name: str
    ip_address: str | None
    auth_token: str | None
    # Start of the scan that this speaker started and that wasn't read yet
    pending_start: float | None = None
    # Start of the unbroken run of read scans; None while broken
    run_start: float | None = None
    # End of what the latest read scan covered
    covered_until: float | None = None
    # When the speaker started keeping trackers from showing away
    uncovered_since: float | None = None
    warned: bool = False

    def covers(self, now: float) -> bool:
        """Return whether the speaker scanned without a break for the whole window."""
        return (
            self.run_start is not None
            and self.covered_until is not None
            and self.run_start <= now - BLUETOOTH_PRESENCE_WINDOW
            and self.covered_until
            >= now - BLUETOOTH_SCAN_INTERVAL - BLUETOOTH_MAX_SCAN_GAP
        )


def evaluate_device_state(
    device: TrackedDevice,
    now: float,
    covered: bool,
    *,
    confirm: bool = True,
    home_confirm: bool = True,
) -> TrackerState:
    """Confirm with new evidence; otherwise retain only the original lease."""
    device.confirmed_now = False
    home = (
        device.last_sighted is not None
        and device.last_sighted > now - BLUETOOTH_PRESENCE_WINDOW
    )
    if home:
        device.pending_departure = None
    delay_until = (
        device.last_sighted + BLUETOOTH_PRESENCE_WINDOW + device.departure_delay
        if device.last_sighted is not None
        else None
    )
    postponing = (
        device.state == TrackerState.HOME
        and device.confirmed_at is not None
        and now < device.confirmed_at + BLUETOOTH_CONFIRMATION_LEASE
        and delay_until is not None
        and now < delay_until
    )
    if confirm and home and home_confirm:
        device.state, device.confirmed_at = TrackerState.HOME, now
        device.confirmed_now = True
    elif confirm and not home and covered:
        if postponing:
            assert device.last_sighted is not None and delay_until is not None
            device.pending_departure = DepartureToken(
                device.policy_generation, device.last_sighted, delay_until
            )
        else:
            device.pending_departure = None
            device.state, device.confirmed_at = TrackerState.NOT_HOME, now
            device.confirmed_now = True
    elif device.confirmed_at is None:
        return TrackerState.UNKNOWN
    elif now - device.confirmed_at >= BLUETOOTH_CONFIRMATION_LEASE:
        return TrackerState.UNAVAILABLE
    return device.state


class BluetoothAccountAdapter:
    """Adapter between GoogleHomeDataUpdateCoordinator and BluetoothScanner."""

    def __init__(
        self,
        coordinator: Any,
        entry: GoogleHomeConfigEntry,
    ) -> None:
        """Initialize adapter."""
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self.config_entry = entry
        self.client = coordinator.client

    @property
    def data(self) -> dict[str, GoogleHomeDevice]:
        """Return devices keyed by device_id."""
        return {dev.device_id: dev for dev in (self.coordinator.data or [])}
