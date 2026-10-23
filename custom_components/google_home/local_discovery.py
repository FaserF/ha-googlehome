"""Recover local addresses from Cast announcements without a Cast HA entity."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from threading import Event
from time import monotonic
from uuid import UUID

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

_SERVICE = "_googlecast._tcp.local."
_DISCOVERY_SECONDS = 3


def normalize_cast_uuid(value: str | None) -> str | None:
    """Return a usable Cast hardware identity, never a placeholder."""
    if not isinstance(value, str):
        return None
    try:
        identity = UUID(value.strip().lower().removeprefix("uuid:"))
    except ValueError:
        return None
    return identity.hex if identity.int else None


@dataclass(frozen=True)
class CastAddress:
    """Keep the advertised Cast UUID separate from HomeGraph's discovery ID."""

    host: str
    cast_uuid: str | None
    discovery_id: str | None


class _AddressListener(ServiceListener):
    """Collect physical receivers during a bounded discovery window."""

    def __init__(self) -> None:
        self.devices: dict[str, CastAddress] = {}
        self.deadline = monotonic() + _DISCOVERY_SECONDS

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.update_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.devices.pop(name, None)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        timeout = min(500, int((self.deadline - monotonic()) * 1000))
        if timeout <= 0 or name.endswith("_sub._googlecast._tcp.local."):
            return
        service = zc.get_service_info(type_, name, timeout=timeout)
        if service is None:
            return

        def text(key: bytes) -> str | None:
            value = service.properties.get(key)
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace") or None
            return value if isinstance(value, str) and value else None

        if text(b"md") == "Google Cast Group":
            return
        addresses = []
        for address in service.parsed_scoped_addresses():
            try:
                parsed = ip_address(address)
            except ValueError:
                continue
            if not parsed.is_unspecified and not parsed.is_multicast:
                addresses.append(parsed)
        if not addresses:
            return
        # Prefer IPv4 when both families are advertised; retain scoped IPv6.
        host = str(min(addresses, key=lambda address: address.version))
        self.devices[name] = CastAddress(
            host, normalize_cast_uuid(text(b"id")), text(b"cd")
        )


def discover_cast_addresses(zeroconf_instance: Zeroconf) -> list[CastAddress]:
    """Run off the event loop; cancel our browser without closing HA's Zeroconf."""
    listener = _AddressListener()
    browser = ServiceBrowser(zeroconf_instance, _SERVICE, listener)
    try:
        Event().wait(_DISCOVERY_SECONDS)
    finally:
        browser.cancel()
    return list(listener.devices.values())
