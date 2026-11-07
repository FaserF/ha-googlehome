"""Diagnostics collector for Google Home Bluetooth scanner."""

from __future__ import annotations

from datetime import timedelta
from time import monotonic
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .coordinator import async_device_disabled

if TYPE_CHECKING:
    from .bluetooth_scanner import BluetoothScanner


def build_scanner_diagnostics(scanner: BluetoothScanner) -> dict[str, object]:
    """Return only speaker scan facts, without credentials or scan contents.

    Coverage is evaluated at download time. Its endpoint is the end of the
    covered scan interval, not when results were read. Convert the monotonic
    endpoint to a wall-clock timestamp using the clocks at download time.
    """
    now = monotonic()
    wall_now = dt_util.utcnow()
    speakers: dict[str, object] = {}
    for device_id in scanner._account.data or {}:
        excluded = device_id in scanner._excluded or async_device_disabled(
            scanner._account.hass, scanner._account.config_entry, device_id
        )
        speaker = scanner._speakers.get(device_id) if not excluded else None
        covered_until = speaker.covered_until if speaker is not None else None
        lease = next(
            (row for row in scanner._leases.values() if row.source_id == device_id),
            None,
        )
        participating = (
            lease is not None
            and now < lease.deadline
            and not excluded
            and device_id not in scanner._unsupported
        )
        speakers[device_id] = {
            "participating": participating,
            "last_success_age": round(max(0, now - lease.last_success), 1)
            if lease is not None
            else None,
            "remaining_lease": round(max(0, lease.deadline - now), 1)
            if lease is not None
            else None,
            "excluded": excluded,
            "unsupported": device_id in scanner._unsupported,
            "answered": device_id in scanner._answered,
            "covers_presence_window": speaker.covers(now) if speaker else False,
            "covered_until": (
                dt_util.as_local(
                    wall_now + timedelta(seconds=covered_until - now)
                ).isoformat()
                if covered_until is not None
                else None
            ),
        }
    return speakers
