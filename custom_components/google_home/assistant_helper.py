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
            # Read synchronously — only called at module import (cache miss never
            # happens inside the event loop because _preload_translations() below
            # populates the cache for all supported languages at import time).
            commands = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as err:
        _LOGGER.warning("Could not load assistant commands file %s: %s", file_path, err)

    _TRANSLATIONS_CACHE[lang] = commands
    return commands


def _preload_translations() -> None:
    """Preload all supported languages at import time so no blocking I/O occurs later."""
    commands_dir = Path(__file__).parent / "assistant_commands"
    if not commands_dir.is_dir():
        return
    for json_file in commands_dir.glob("*.json"):
        lang_code = json_file.stem
        if lang_code not in _TRANSLATIONS_CACHE:
            _load_translations(lang_code)


# Preload at import time (module-level, synchronous — never inside the event loop)
_preload_translations()


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
