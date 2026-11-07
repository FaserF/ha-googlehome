"""Subentry config flow for tracked Bluetooth devices."""

from __future__ import annotations

import logging

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]
from homeassistant.config_entries import (
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .bluetooth import parse_irk, parse_mac
from .const import (
    CONF_ADDITIONAL_DEPARTURE_DELAY,
    CONF_BLUETOOTH_TRACKING,
    CONF_IRK,
    CONF_IRK_OR_MAC,
    DEPARTURE_DELAY_VALUES,
    SUBENTRY_BLUETOOTH_DEVICE,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


class BluetoothDeviceSubentryFlow(ConfigSubentryFlow):
    """Add a tracked Bluetooth device or adjust its departure timing."""

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> SubentryFlowResult:
        """Ask for the device's name, and its IRK or MAC address in one field."""
        entry = self._get_entry()
        if not entry.options.get(CONF_BLUETOOTH_TRACKING):
            return self.async_abort(reason="bluetooth_tracking_off")
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            value = user_input.get(CONF_IRK_OR_MAC, "").strip()
            delay = int(user_input.get(CONF_ADDITIONAL_DEPARTURE_DELAY, "0"))
            data: dict[str, str | int] = {}
            if not name:
                errors[CONF_NAME] = "name_empty"
            elif not value:
                errors[CONF_IRK_OR_MAC] = "irk_or_mac"
            elif (address := parse_mac(value)) is not None:
                data = {CONF_MAC: address}
            elif (irk := parse_irk(value)) is not None:
                data = {CONF_IRK: irk.hex()}
            else:
                errors[CONF_IRK_OR_MAC] = (
                    "mac_invalid" if len(value) <= 17 else "irk_invalid"
                )
            if (
                data
                and hasattr(entry, "get_subentries_of_type")
                and any(
                    (subentry.data.get(CONF_IRK), subentry.data.get(CONF_MAC))
                    == (data.get(CONF_IRK), data.get(CONF_MAC))
                    for subentry in entry.get_subentries_of_type(
                        SUBENTRY_BLUETOOTH_DEVICE
                    )
                )
            ):
                errors["base"] = "already_tracked"
            elif data and not errors:
                if delay:
                    data[CONF_ADDITIONAL_DEPARTURE_DELAY] = delay
                return self.async_create_entry(title=name, data=data)

        delay_options = [
            SelectOptionDict(value=str(s), label=f"{s} s")
            for s in DEPARTURE_DELAY_VALUES
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_IRK_OR_MAC): str,
                    vol.Optional(
                        CONF_ADDITIONAL_DEPARTURE_DELAY, default="0"
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=delay_options,
                            mode=SelectSelectorMode.LIST,
                            translation_key="departure_delay",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, str] | None = None
    ) -> SubentryFlowResult:
        """Change only timing, retaining the current identity and subentry."""
        entry = self._get_entry()
        try:
            subentry = self._get_reconfigure_subentry()
        except Exception:
            return self.async_abort(reason="device_removed")
        if user_input is not None:
            return self.async_update_and_abort(
                entry,
                subentry,
                data_updates={
                    CONF_ADDITIONAL_DEPARTURE_DELAY: int(
                        user_input[CONF_ADDITIONAL_DEPARTURE_DELAY]
                    )
                },
            )
        delay_options = [
            SelectOptionDict(value=str(s), label=f"{s} s")
            for s in DEPARTURE_DELAY_VALUES
        ]
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ADDITIONAL_DEPARTURE_DELAY,
                        default=str(
                            subentry.data.get(CONF_ADDITIONAL_DEPARTURE_DELAY, 0)
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=delay_options,
                            mode=SelectSelectorMode.LIST,
                            translation_key="departure_delay",
                        )
                    ),
                }
            ),
        )
