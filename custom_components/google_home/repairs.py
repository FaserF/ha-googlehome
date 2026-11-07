"""The fixes of the repairs about polling and the update interval."""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from . import async_show_polling_disabled, const, saved_interval
from .const import (
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    INTEGRATION_PAGE_URL,
    INTERVAL_DOCS_URL,
    ISSUE_INVALID_INTERVAL,
    ISSUE_POLLING_DISABLED,
    POLLING_DOCS_URL,
)


class PollingDisabledFlow(RepairsFlow):
    """Turn polling back on, or keep it off and hide the repair."""

    async def async_step_init(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Say what polling being off means, and offer both choices."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["turn_on", "keep_off"],
            description_placeholders={"docs_url": POLLING_DOCS_URL},
        )

    async def async_step_turn_on(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Turn polling on and reload the entry, as the system options do.

        Home Assistant then removes the repair.
        """
        entries = self.hass.config_entries
        if self.data is not None and (
            entry := entries.async_get_entry(str(self.data["entry_id"]))
        ):
            entries.async_update_entry(entry, pref_disable_polling=False)
            entries.async_schedule_reload(entry.entry_id)
        return self.async_create_entry(data={})

    async def async_step_keep_off(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Hide the repair and leave polling off."""
        if not ir.async_get(self.hass).async_get_issue(DOMAIN, ISSUE_POLLING_DISABLED):
            return self.async_create_entry(data={})
        ir.async_ignore_issue(self.hass, DOMAIN, ISSUE_POLLING_DISABLED, True)
        return self.async_abort(reason="polling_kept_off")


class InvalidIntervalFlow(RepairsFlow):
    """Save the default update interval, and turn off polling if the user chooses."""

    def _entry(self) -> ConfigEntry | None:
        """Return the entry, unless it was deleted while the fix was open."""
        if self.data is None:
            return None
        return self.hass.config_entries.async_get_entry(str(self.data["entry_id"]))

    async def async_step_init(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Name the saved interval, and offer to save the default or turn polling off."""
        if (
            (entry := self._entry()) is None
            or (seconds := saved_interval(entry)) >= const.MIN_UPDATE_INTERVAL
            or entry.pref_disable_polling
        ):
            return self.async_create_entry(data={})
        return self.async_show_menu(
            step_id="init",
            menu_options=["use_default", "turn_off_polling"],
            description_placeholders={
                "interval": str(seconds),
                "min_interval": str(const.MIN_UPDATE_INTERVAL),
                "default_interval": str(const.UPDATE_INTERVAL),
                "docs_url": INTERVAL_DOCS_URL,
                "integration_url": INTEGRATION_PAGE_URL,
            },
        )

    async def async_step_use_default(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Save the default interval, which applies without a reload."""
        if entry := self._entry():
            self.hass.config_entries.async_update_entry(
                entry, options=default_interval_options(entry)
            )
        return self.async_create_entry(data={})

    async def async_step_turn_off_polling(
        self, _user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Save the default interval, turn polling off and reload, as the system options do."""
        if entry := self._entry():
            self.hass.config_entries.async_update_entry(
                entry,
                options=default_interval_options(entry),
                pref_disable_polling=True,
            )
            async_show_polling_disabled(self.hass, entry)
            ir.async_ignore_issue(self.hass, DOMAIN, ISSUE_POLLING_DISABLED, True)
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return self.async_create_entry(data={})


def default_interval_options(entry: ConfigEntry) -> dict[str, object]:
    """Return the options with the default interval, unless a valid one was saved meanwhile."""
    if saved_interval(entry) >= const.MIN_UPDATE_INTERVAL:
        return dict(entry.options)
    return {**entry.options, CONF_UPDATE_INTERVAL: const.UPDATE_INTERVAL}


async def async_create_fix_flow(
    _hass: HomeAssistant,
    issue_id: str,
    _data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix of a fixable repair."""
    if issue_id == ISSUE_INVALID_INTERVAL:
        return InvalidIntervalFlow()
    return PollingDisabledFlow()
