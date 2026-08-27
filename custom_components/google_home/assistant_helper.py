"""Helper utilities for Google Home Assistant SDK command formatting loaded from translations."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER: logging.Logger = logging.getLogger(__package__)

_TRANSLATIONS_CACHE: dict[str, dict[str, str]] = {}


def _load_translations(lang: str) -> dict[str, str]:
    """Load assistant commands from assistant_commands/{lang}.json with cache."""
    if lang in _TRANSLATIONS_CACHE:
        return _TRANSLATIONS_CACHE[lang]

    commands_dir = Path(__file__).parent / "assistant_commands"
    file_path = commands_dir / f"{lang}.json"

    if not file_path.exists():
        file_path = commands_dir / "en.json"

    commands: dict[str, str] = {}
    try:
        if file_path.exists():
            with open(file_path, encoding="utf-8") as f:
                commands = json.load(f)
    except Exception as err:
        _LOGGER.warning("Could not load assistant commands file %s: %s", file_path, err)

    _TRANSLATIONS_CACHE[lang] = commands
    return commands


def get_assistant_language(hass: HomeAssistant) -> str:
    """Return configured HA language code (defaults/fallbacks to 'en')."""
    lang = getattr(getattr(hass, "config", None), "language", "en")
    if isinstance(lang, str) and lang.lower().startswith("de"):
        return "de"
    return "en"


def format_command(
    hass: HomeAssistant,
    action: str,
    device_name: str,
    **kwargs: Any,
) -> str:
    """Format Google Assistant text command loaded from i18n translation json files."""
    lang = get_assistant_language(hass)
    cmds = _load_translations(lang)

    # Fallback to english if action missing in current language
    if action not in cmds and lang != "en":
        cmds = _load_translations("en")

    template = cmds.get(action)
    if not template:
        # Fallback default
        return f"Turn on {device_name}"

    format_args = {"device_name": device_name, **kwargs}
    try:
        return template.format(**format_args)
    except KeyError:
        return template
