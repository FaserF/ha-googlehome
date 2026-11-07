"""Re-authentication flow mixin for Google Home config flow."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import GlocaltokensApiClient
from .const import CONF_MASTER_TOKEN
from .exceptions import AuthenticationFailed, InvalidMasterToken

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)


class ReauthFlowMixin:
    """Mixin providing re-authentication steps for GoogleHomeFlowHandler."""

    if TYPE_CHECKING:
        hass: Any
        _username: str | None
        _master_token: str | None
        _addon_host: str
        _errors: dict[str, str]

        def _get_reauth_entry(self) -> ConfigEntry: ...
        def async_show_form(self, **kwargs: Any) -> ConfigFlowResult: ...
        def async_update_reload_and_abort(
            self, entry: ConfigEntry, **kwargs: Any
        ) -> ConfigFlowResult: ...
        async def _async_probe_addon(
            self,
        ) -> tuple[str | None, dict[str, Any] | None]: ...
        async def async_step_token(
            self, user_input: dict[str, Any] | None = None
        ) -> ConfigFlowResult: ...
        async def async_step_addon(
            self, user_input: dict[str, Any] | None = None
        ) -> ConfigFlowResult: ...

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication initiation."""
        self._username = str(entry_data.get("username", ""))
        self._errors = {}

        # 1. Probe for running Google Home Token Hub add-on
        found_host, addon_session = await self._async_probe_addon()
        if (
            found_host
            and addon_session
            and addon_session.get("master_token")
            and (
                not self._username
                or addon_session.get("email", "").strip().lower()
                == self._username.strip().lower()
            )
        ):
            self._addon_host = found_host
            self._master_token = addon_session.get("master_token")
            if not self._username:
                self._username = addon_session.get("email")
            return await self.async_step_reauth_addon()

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_addon(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm applying the new Master Token discovered from Google Home Token Hub Add-on."""
        self._errors = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            choice = user_input.get("reauth_action", "apply_addon_token")
            if choice == "apply_addon_token" and self._master_token:
                session = async_get_clientsession(self.hass)
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=session,
                    username=self._username or "",
                    master_token=self._master_token,
                )
                try:
                    await client.get_access_token()
                except (AuthenticationFailed, InvalidMasterToken):
                    self._errors["base"] = "invalid_master_token"
                except Exception as err:
                    _LOGGER.exception(
                        "Error validating addon token during reauth: %s", err
                    )
                    self._errors["base"] = "unknown"
                else:
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data={
                            **reauth_entry.data,
                            CONF_MASTER_TOKEN: self._master_token,
                        },
                        options={
                            **reauth_entry.options,
                            CONF_MASTER_TOKEN: self._master_token,
                        },
                    )
            else:
                return await self.async_step_reauth_confirm()

        data_schema = vol.Schema(
            {
                vol.Required(
                    "reauth_action", default="apply_addon_token"
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=["apply_addon_token", "enter_manually"],
                        translation_key="reauth_action",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="reauth_addon",
            data_schema=data_schema,
            errors=self._errors,
            description_placeholders={
                "username": self._username or "Google Account",
            },
        )

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication and route user to preferred re-auth method."""
        self._errors = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            method = user_input.get("reauth_method", "token")
            if method == "addon":
                # User chose to log in via Addon
                return await self.async_step_addon()
            # Default: route to token input step (user pastes fresh token from browser)
            return await self.async_step_token()

        data_schema = vol.Schema(
            {
                vol.Required("reauth_method", default="token"): SelectSelector(
                    SelectSelectorConfig(
                        options=["token", "addon"],
                        translation_key="reauth_method",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=data_schema,
            errors=self._errors,
            description_placeholders={
                "username": (
                    reauth_entry.data.get("username")
                    or self._username
                    or "Google Account"
                ),
            },
        )
