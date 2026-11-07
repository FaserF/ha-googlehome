"""Bluetooth presence tracking for Google Home integration.

This module re-exports scanner, models, and API utilities from their
dedicated modules for backwards-compatibility.
"""

from __future__ import annotations

from .bluetooth_api import (
    BluetoothScanError,
    BluetoothScanUnsupported,
    async_get_bluetooth_scan_results,
    async_start_bluetooth_scan,
    bluetooth_now,
)
from .bluetooth_diagnostics import build_scanner_diagnostics
from .bluetooth_models import (
    IRK_LENGTH,
    BluetoothAccountAdapter,
    DepartureToken,
    SpeakerScan,
    TrackedDevice,
    TrackerState,
    TrackerUpdate,
    configured_departure_delay,
    evaluate_device_state,
    normalize_mac,
    parse_irk,
    parse_mac,
)
from .bluetooth_scanner import BluetoothScanner
from .coordinator import async_device_disabled

__all__ = [
    "IRK_LENGTH",
    "BluetoothAccountAdapter",
    "BluetoothScanError",
    "BluetoothScanUnsupported",
    "BluetoothScanner",
    "DepartureToken",
    "SpeakerScan",
    "TrackedDevice",
    "TrackerState",
    "TrackerUpdate",
    "async_device_disabled",
    "async_get_bluetooth_scan_results",
    "async_start_bluetooth_scan",
    "bluetooth_now",
    "build_scanner_diagnostics",
    "configured_departure_delay",
    "evaluate_device_state",
    "normalize_mac",
    "parse_irk",
    "parse_mac",
]
