"""Parse volume telemetry without confusing missing data with zero volume."""

import math
from collections.abc import Mapping
from typing import Any


def volume_percentage(value: Any, *, normalized: bool | None = None) -> float | None:
    """Convert normalized levels or percentage telemetry to a valid percentage."""
    if isinstance(value, bool):
        return None
    try:
        level = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(level) or level < 0 or level > (1 if normalized else 100):
        return None
    if normalized is True or (normalized is None and level <= 1):
        level *= 100
    return float(round(level))


def read_volume_percentage(data: Any) -> float | None:
    """Read supported local API fields, including nested volume objects."""
    if not isinstance(data, Mapping):
        return None
    for key in ("volume", "level", "current_volume"):
        value = data.get(key)
        if isinstance(value, Mapping):
            result = read_volume_percentage(value)
        else:
            result = volume_percentage(value)
        if result is not None:
            return result
    return None
