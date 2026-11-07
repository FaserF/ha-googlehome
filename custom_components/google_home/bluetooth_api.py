"""Bluetooth scan HTTP API for Google Home speakers."""

from __future__ import annotations

import logging
from http import HTTPStatus
from time import monotonic
from typing import Literal, cast

from aiohttp import ClientError, ClientSession, ClientTimeout
from aiohttp.client_exceptions import ContentTypeError

from .const import (
    API_ENDPOINT_BLUETOOTH_RESULTS,
    API_ENDPOINT_BLUETOOTH_SCAN,
    BLUETOOTH_SCAN_INTERVAL,
    BLUETOOTH_TIMEOUT,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
    PORT,
)
from .device_info import create_url
from .models import GoogleHomeDevice
from .types import BluetoothJsonDict, JsonDict

_LOGGER: logging.Logger = logging.getLogger(__package__)


class BluetoothScanError(Exception):
    """Error to indicate a device didn't start a Bluetooth scan or return its results."""


class BluetoothScanUnsupported(BluetoothScanError):
    """Error to indicate a device has no Bluetooth scan endpoint."""


async def async_start_bluetooth_scan(
    session: ClientSession, device: GoogleHomeDevice
) -> None:
    """Start a Bluetooth scan that clears the results of the previous one.

    The speaker scans for up to one update interval, then stops on its own, also
    after the integration unloads. The next Bluetooth update reads the results.
    """
    await _async_bluetooth_request(
        session,
        "POST",
        API_ENDPOINT_BLUETOOTH_SCAN,
        device,
        {"enable": True, "clear_results": True, "timeout": BLUETOOTH_SCAN_INTERVAL},
    )


async def async_get_bluetooth_scan_results(
    session: ClientSession, device: GoogleHomeDevice
) -> list[BluetoothJsonDict]:
    """Return the Bluetooth devices the device heard since its scan started."""
    response = await _async_bluetooth_request(
        session, "GET", API_ENDPOINT_BLUETOOTH_RESULTS, device
    )
    if not isinstance(response, list):
        raise BluetoothScanError(f"{device.name} returned no list of results")
    return [
        {"mac_address": result["mac_address"], "rssi": result["rssi"]}
        for result in cast(list[object], response)
        if isinstance(result, dict)
        and isinstance(result.get("mac_address"), str)
        and isinstance(result.get("rssi"), int)
    ]


async def _async_bluetooth_request(
    session: ClientSession,
    method: Literal["GET", "POST"],
    endpoint: str,
    device: GoogleHomeDevice,
    data: JsonDict | None = None,
) -> object:
    """Send a Bluetooth request and return its JSON response.

    Unlike the client's requests, a failure leaves the device's availability alone
    and raises instead of logging, as Bluetooth updates run every 30 seconds. The
    device has less time to answer than the client's requests give it, so that scan
    results are read while they're fresh enough to use.
    """
    if not device.ip_address or not device.auth_token:
        raise BluetoothScanError(f"{device.name} has no IP address or auth token")
    url = create_url(device.ip_address, PORT, endpoint)
    headers = {
        HEADER_CAST_LOCAL_AUTH: device.auth_token,
        HEADER_CONTENT_TYPE: "application/json",
    }
    try:
        async with session.request(
            method,
            url,
            json=data,
            headers=headers,
            timeout=ClientTimeout(total=BLUETOOTH_TIMEOUT),
        ) as response:
            if response.status == HTTPStatus.NOT_FOUND:
                raise BluetoothScanUnsupported(f"{device.name} returned 404")
            if response.status != HTTPStatus.OK:
                raise BluetoothScanError(f"{device.name} returned {response.status}")
            try:
                return cast(object, await response.json())
            except ContentTypeError:
                return None
    except (ClientError, TimeoutError, ValueError) as err:
        raise BluetoothScanError(f"{device.name} didn't answer: {err!r}") from err


def bluetooth_now() -> float:
    """Use the scanner clock for setup, expiry and accepted replies alike."""
    return monotonic()
