"""Add-on specific config flow steps for Google Home."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ADDON_ACTION,
    CONF_ADDON_HOST,
    CONF_ADDON_PORT,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_ADDON_HOST,
    DEFAULT_ADDON_PORT,
)

if TYPE_CHECKING:
    pass

_LOGGER: logging.Logger = logging.getLogger(__package__)


class AddonFlowMixin:
    """Mixin providing Add-on steps to GoogleHomeFlowHandler."""

    if TYPE_CHECKING:
        hass: Any
        _username: str | None
        _master_token: str | None
        _addon_host: str
        _addon_port: int
        _errors: dict[str, str]
        _discovered_device_name: str | None
        _discovery_source: str

        def async_show_form(self, **kwargs: Any) -> ConfigFlowResult: ...
        async def _async_probe_addon(
            self,
        ) -> tuple[str | None, dict[str, Any] | None]: ...
        async def async_step_mode(
            self, user_input: dict[str, Any] | None = None
        ) -> ConfigFlowResult: ...

    async def _async_connect_addon(self, host: str, port: int) -> ConfigFlowResult:
        """Connect to Google Home Token Hub Add-on and fetch session."""
        self._addon_host = host
        self._addon_port = port
        session = async_get_clientsession(self.hass)
        url = f"http://{host}:{port}/api/v1/session"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    master_token = data.get("master_token")
                    email = data.get("email")
                    if master_token and email:
                        self._username = email
                        self._master_token = master_token
                        return await self.async_step_addon_existing()
        except Exception as err:
            _LOGGER.debug("Add-on connection attempt failed: %s", err)

        return await self.async_step_addon_login()

    async def async_step_addon_existing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt user whether to use existing Master Token or generate a new one."""
        if user_input is not None:
            action = user_input.get("existing_action", "use_existing")
            if action == "use_existing":
                return await self.async_step_addon_action()
            self._master_token = None
            return await self.async_step_addon_login()

        data_schema = vol.Schema(
            {
                vol.Required("existing_action", default="use_existing"): SelectSelector(
                    SelectSelectorConfig(
                        options=["use_existing", "generate_new"],
                        translation_key="existing_action",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="addon_existing",
            data_schema=data_schema,
            description_placeholders={
                "email": self._username or "Google Account",
            },
        )

    async def async_step_addon_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Seamlessly perform login on the Add-on directly from Home Assistant UI."""
        self._errors = {}
        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=self._username or ""): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        if user_input is not None:
            email = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "").strip()

            if not email or "@" not in email or "." not in email:
                self._errors["base"] = "invalid_email"
            elif not password:
                self._errors["base"] = "missing_credentials"
            else:
                session = async_get_clientsession(self.hass)
                url = f"http://{self._addon_host}:{self._addon_port}/api/auth/start"
                try:
                    async with session.post(
                        url,
                        json={"email": email, "password": password},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        data = await resp.json()
                        if resp.status == 200 and data.get("success"):
                            self._username = email
                            self._master_token = data.get("master_token")
                            return await self.async_step_addon_action()
                        elif resp.status == 200 and data.get("requires_2fa"):
                            self._username = email
                            return await self.async_step_addon_2fa()
                        else:
                            err_detail = data.get("detail", "")
                            if (
                                "BadAuthentication" in err_detail
                                or "2FA_REQUIRED" in err_detail
                            ):
                                self._username = email
                                return await self.async_step_addon_2fa()
                            else:
                                self._errors["base"] = "invalid_auth"
                except Exception as err:
                    _LOGGER.exception("Error during addon login: %s", err)
                    self._errors["base"] = "cannot_connect_addon"

        discovery_intro = ""
        if self._discovery_source == "zeroconf_with_addon":
            discovery_intro = f"🎉 **{self._discovered_device_name or 'Google Home'}** & active **Google Home Token Hub Add-on** automatically discovered!\n\n"
        elif self._discovery_source == "hassio":
            discovery_intro = "🚀 Active **Google Home Token Hub Add-on** automatically discovered!\n\n"

        return self.async_show_form(
            step_id="addon_login",
            data_schema=data_schema,
            errors=self._errors,
            description_placeholders={
                "discovery_intro": discovery_intro,
                "setup_url": "https://accounts.google.com/EmbeddedSetup",
            },
        )

    async def async_step_addon_2fa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle interactive authentication monitoring step for Add-on."""
        self._errors = {}
        session = async_get_clientsession(self.hass)
        base_url = f"http://{self._addon_host}:{self._addon_port}"

        async def get_status() -> dict:
            try:
                async with session.get(
                    f"{base_url}/api/auth/status",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception:
                pass
            return {}

        if user_input is not None:
            code = user_input.get("two_factor_code", "").strip()
            if code:
                try:
                    await session.post(
                        f"{base_url}/api/auth/2fa",
                        json={"code": code},
                        timeout=aiohttp.ClientTimeout(total=10),
                    )
                except Exception as err:
                    _LOGGER.debug("Error submitting 2FA code: %s", err)

            for _ in range(10):
                await asyncio.sleep(1.0)
                data = await get_status()
                if data.get("is_logged_in") and data.get("master_token"):
                    self._master_token = data["master_token"]
                    return await self.async_step_addon_action()
                if data.get("error"):
                    self._errors["base"] = "invalid_auth"
                    break

        # Poll and wait up to 45 seconds while the add-on is performing automatic steps
        # (navigating, filling email, filling password, exchanging token).
        # Only stop waiting if:
        # 1. Login succeeded with master token
        # 2. An error occurred
        # 3. 2FA interaction is actually required from the user
        if user_input is None:
            for _ in range(45):  # up to 45s (0.5s interval)
                data = await get_status()
                step = data.get("step", "starting")

                if data.get("is_logged_in") and data.get("master_token"):
                    self._master_token = data["master_token"]
                    return await self.async_step_addon_action()

                if data.get("error"):
                    break

                # Stop waiting and show form immediately if user input/interaction is needed
                if step.startswith("2fa"):
                    break

                await asyncio.sleep(1.0)

        data = await get_status()
        if data.get("is_logged_in") and data.get("master_token"):
            self._master_token = data["master_token"]
            return await self.async_step_addon_action()

        err = data.get("error")
        step = data.get("step", "starting")
        two_factor = data.get("two_factor") or {}

        if err:
            self._errors["base"] = "invalid_auth"
            two_factor_instruction = f"❌ **Authentication failed:** {err}"
        elif step == "starting":
            two_factor_instruction = "⏳ Starting Google authentication..."
        elif step == "navigating":
            two_factor_instruction = "🌐 Connecting to Google..."
        elif step == "filling_email":
            two_factor_instruction = "📧 Entering Google account email..."
        elif step == "filling_password":
            two_factor_instruction = "🔑 Verifying password with Google..."
        elif step == "2fa_prompt" and two_factor.get("number"):
            two_factor_instruction = (
                f"📱 **Google sent a security prompt to your phone.**\n\n"
                f"Tap the number **{two_factor['number']}** on your smartphone to approve the login."
            )
        elif step == "2fa_code":
            two_factor_instruction = "🔐 **Enter the 6-digit verification code** from your SMS or Authenticator App below."
        elif step == "2fa_general":
            two_factor_instruction = "📱 **Google is waiting for confirmation on your smartphone.**\n\nPlease tap 'Yes' or approve the prompt."
        elif step == "exchanging":
            two_factor_instruction = (
                "✨ Authentication successful – generating Master Token..."
            )
        elif step == "success":
            two_factor_instruction = "✅ Done! Finalizing..."
        elif step == "idle":
            two_factor_instruction = "⚠️ Authentication was cancelled or not started."
        else:
            two_factor_instruction = f"⏳ Authenticating with Google... ({step})"

        needs_code = step in ("2fa_code", "2fa_prompt", "2fa_general")
        data_schema = (
            vol.Schema({vol.Optional("two_factor_code"): str})
            if needs_code
            else vol.Schema({})
        )

        return self.async_show_form(
            step_id="addon_2fa",
            data_schema=data_schema,
            errors=self._errors,
            description_placeholders={
                "two_factor_instruction": two_factor_instruction,
            },
        )

    async def async_step_addon_action(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer user choice to stop/uninstall add-on or keep it running."""
        if user_input is not None:
            action = user_input.get(CONF_ADDON_ACTION, "stop")
            supervisor_token = os.getenv("SUPERVISOR_TOKEN")

            if supervisor_token and action in ("stop", "uninstall"):
                session = async_get_clientsession(self.hass)
                headers = {"Authorization": f"Bearer {supervisor_token}"}
                for slug in ("googlehome", "local_googlehome", "edge_googlehome"):
                    target_url = f"http://supervisor/addons/{slug}/{action}"
                    try:
                        async with session.post(
                            target_url,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status in (200, 201):
                                _LOGGER.info(
                                    "Successfully triggered %s on add-on %s",
                                    action,
                                    slug,
                                )
                                break
                    except Exception as exc:
                        _LOGGER.debug(
                            "Addon supervisor %s call failed: %s", action, exc
                        )

            return await self.async_step_mode()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDON_ACTION, default="stop"): SelectSelector(
                    SelectSelectorConfig(
                        options=["stop", "uninstall", "keep_running"],
                        translation_key="addon_action",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="addon_action",
            data_schema=data_schema,
            description_placeholders={"email": self._username or ""},
        )

    async def async_step_addon(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Add-on selection or manual host entry."""
        self._errors = {}

        found_host, found_data = await self._async_probe_addon()
        if found_host:
            return await self._async_connect_addon(found_host, DEFAULT_ADDON_PORT)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDON_HOST, default=DEFAULT_ADDON_HOST): str,
                vol.Required(CONF_ADDON_PORT, default=DEFAULT_ADDON_PORT): int,
            }
        )

        if user_input is not None:
            host = user_input.get(CONF_ADDON_HOST, DEFAULT_ADDON_HOST).strip()
            port = int(user_input.get(CONF_ADDON_PORT, DEFAULT_ADDON_PORT))
            return await self._async_connect_addon(host, port)

        return self.async_show_form(
            step_id="addon",
            data_schema=data_schema,
            errors=self._errors,
        )
