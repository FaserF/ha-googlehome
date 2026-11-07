"""Device info and URL creation helpers for Google Home devices."""

from __future__ import annotations

from .const import PORT


def create_url(ip_address: str, port: int | str = PORT, endpoint: str = "") -> str:
    """Create URL for device HTTP request, properly escaping IPv6 if present."""
    if isinstance(port, str) and not endpoint:
        endpoint = port
        port = PORT
    host = (
        f"[{ip_address}]"
        if ":" in ip_address and not ip_address.startswith("[")
        else ip_address
    )
    return f"https://{host}:{port}/{endpoint}"


__all__ = ["create_url"]
