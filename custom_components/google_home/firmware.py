"""Keep Cast speaker firmware and Nest display system versions distinct."""

from collections.abc import Mapping
from typing import Any


def firmware_version_family(version: str | None) -> str | None:
    """Identify the version families published in Google's firmware catalog."""
    if not version:
        return None
    parts = version.split(".")
    if not all(part.isdecimal() for part in parts):
        return None
    if len(parts) == 3:
        return "cast"
    if len(parts) == 4 and len(parts[1]) == 8:
        return "system"
    return None


def extract_firmware_versions(
    data: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Return installed, Cast, and system versions from a local Eureka response.

    Speakers use Cast firmware. Displays also report a separate system version,
    which is the version Google publishes for Nest Hub updates.
    """
    blocks = [
        block
        for block in (data.get("build_info"), data, data.get("device_info"))
        if isinstance(block, Mapping)
    ]
    cast = next(
        (
            str(block[key]).strip()
            for block in blocks
            for key in ("cast_build_revision", "build_version")
            if block.get(key)
        ),
        None,
    )
    system = next(
        (
            str(block["system_build_number"]).strip()
            for block in blocks
            if block.get("system_build_number")
        ),
        None,
    )
    fallback = data.get("version")
    if firmware_version_family(system) == "system":
        installed = system
    else:
        installed = cast or system or (fallback if isinstance(fallback, str) else None)
    return installed, cast, system
