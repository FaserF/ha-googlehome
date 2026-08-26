"""Config flow for Google Home integration."""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import GlocaltokensApiClient
from .const import (
    ADDON_CONTAINER_HOSTS,
    AUTH_METHOD_ADDON,
    AUTH_METHOD_APP_PASSWORD,
    AUTH_METHOD_CREDENTIALS,
    AUTH_METHOD_TOKEN,
    CONF_ADDON_ACTION,
    CONF_ADDON_HOST,
    CONF_ADDON_PORT,
    CONF_AUTH_METHOD,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DEFAULT_ADDON_HOST,
    DEFAULT_ADDON_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_PASSWORD_LENGTH,
)
from .exceptions import (
    AdvancedProtectionActive,
    AuthenticationFailed,
    InvalidMasterToken,
    TwoFactorRequired,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Google Home."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize."""
        self._username: str | None = None
        self._master_token: str | None = None
        self._addon_host: str = DEFAULT_ADDON_HOST
        self._addon_port: int = DEFAULT_ADDON_PORT
        self._errors: dict[str, str] = {}

    async def _async_probe_addon(self) -> tuple[str | None, dict[str, Any] | None]:
        """Probe potential add-on hosts (stable, edge, local) to find active addon."""
        session = async_get_clientsession(self.hass)
        for host in ADDON_CONTAINER_HOSTS:
            url = f"http://{host}:{DEFAULT_ADDON_PORT}/api/v1/session"
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=2)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return host, data
            except Exception:
                continue
        return None, None

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle Home Assistant Supervisor auto-discovery from googlehome add-on."""
        _LOGGER.info(
            "Supervisor auto-discovered Google Home Add-on: %s", discovery_info
        )
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        host = discovery_info.config.get("host", DEFAULT_ADDON_HOST)
        port = int(discovery_info.config.get("port", DEFAULT_ADDON_PORT))
        return await self._async_connect_addon(host, port)

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
                        return await self.async_step_addon_action()
        except Exception as err:
            _LOGGER.debug("Add-on connection attempt failed: %s", err)

        # Add-on is reachable but user hasn't logged in yet -> route directly to seamless HA login
        return await self.async_step_addon_login()

    async def async_step_addon_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Seamlessly perform login on the Add-on directly from Home Assistant UI."""
        self._errors = {}
        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=self._username or ""): str,
                vol.Optional(CONF_PASSWORD): str,
                vol.Optional(CONF_MASTER_TOKEN): str,
            }
        )

        if user_input is not None:
            email = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "").strip()
            token = user_input.get(CONF_MASTER_TOKEN, "").strip()

            if not email:
                self._errors["base"] = "invalid_auth"
            elif not password and not token:
                self._errors["base"] = "missing_credentials"
            else:
                session = async_get_clientsession(self.hass)
                url = f"http://{self._addon_host}:{self._addon_port}/api/login"
                try:
                    async with session.post(
                        url,
                        json={"email": email, "password": password, "token": token},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        data = await resp.json()
                        if resp.status == 200 and data.get("success"):
                            self._username = email
                            self._master_token = data.get("master_token")
                            return await self.async_step_addon_action()
                        else:
                            err_detail = data.get("detail", "")
                            if "BadAuthentication" in err_detail:
                                self._errors["base"] = "two_factor_required"
                            else:
                                self._errors["base"] = "invalid_auth"
                except Exception as err:
                    _LOGGER.exception("Error during addon login: %s", err)
                    self._errors["base"] = "cannot_connect_addon"

        return self.async_show_form(
            step_id="addon_login",
            data_schema=data_schema,
            errors=self._errors,
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
                # Check for standard googlehome addon slug
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

            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Google Home ({self._username})"
                if self._username
                else "Google Home",
                data={
                    CONF_AUTH_METHOD: AUTH_METHOD_ADDON,
                    CONF_USERNAME: self._username,
                    CONF_MASTER_TOKEN: self._master_token,
                    CONF_ADDON_HOST: self._addon_host,
                    CONF_ADDON_PORT: self._addon_port,
                },
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDON_ACTION, default="stop"): vol.In(
                    {
                        "stop": "Add-on stoppen (Empfohlen - spart RAM/CPU, Token ist gesichert)",
                        "uninstall": "Add-on deinstallieren (Wird nicht mehr benötigt)",
                        "keep_running": "Add-on weiterlaufen lassen",
                    }
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

        # Auto-probe for any running addon container first
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

    async def async_step_zeroconf(self, discovery_info: Any) -> ConfigFlowResult:
        """Handle zeroconf discovery of Google Cast / Home devices."""
        # Abort if Google Home is already set up in Home Assistant
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        # Extract device friendly name from mDNS properties ('fn') if available
        device_name = "Google Home"
        properties = getattr(discovery_info, "properties", {})
        if isinstance(properties, dict) and "fn" in properties:
            fn_val = properties["fn"]
            if isinstance(fn_val, bytes):
                try:
                    device_name = fn_val.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            elif isinstance(fn_val, str):
                device_name = fn_val

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {"name": device_name}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step: select authentication method."""
        self._errors = {}

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            method = user_input.get(CONF_AUTH_METHOD, AUTH_METHOD_TOKEN)
            if method == AUTH_METHOD_TOKEN:
                return await self.async_step_token()
            if method == AUTH_METHOD_ADDON:
                return await self.async_step_addon()
            if method == AUTH_METHOD_APP_PASSWORD:
                return await self.async_step_app_password()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_AUTH_METHOD, default=AUTH_METHOD_TOKEN): vol.In(
                    {
                        AUTH_METHOD_TOKEN: "Token (Master Token / Web OAuth Token) [Recommended]",
                        AUTH_METHOD_ADDON: "Google Home Token Hub Add-on (Ingress Hub)",
                        AUTH_METHOD_APP_PASSWORD: "App Password (Username + App Password)",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=self._errors,
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Token authentication (Master Token or Web OAuth Token)."""
        self._errors = {}
        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_MASTER_TOKEN): str,
            }
        )

        if user_input is not None:
            username = user_input.get(CONF_USERNAME, "").strip()
            master_token = user_input.get(CONF_MASTER_TOKEN, "").strip()
            session = async_get_clientsession(self.hass)

            clean_token = master_token
            if clean_token.startswith("oauth_token="):
                clean_token = clean_token.split("oauth_token=")[1].split(";")[0].strip()

            client = GlocaltokensApiClient(
                hass=self.hass,
                session=session,
                username=username if username else None,
                master_token=clean_token if clean_token.startswith("aas_et/") else None,
            )

            try:
                if not clean_token.startswith("aas_et/"):
                    if not username:
                        self._errors["base"] = "missing_email_for_oauth"
                        return self.async_show_form(
                            step_id="token",
                            data_schema=data_schema,
                            errors=self._errors,
                        )
                    master_token = await client.exchange_web_token(clean_token)
                else:
                    master_token = clean_token
                    await client.get_access_token()
            except (InvalidMasterToken, AuthenticationFailed):
                if "base" not in self._errors:
                    self._errors["base"] = "invalid_master_token"
            except Exception as err:
                _LOGGER.exception("Unexpected error validating token: %s", err)
                self._errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Google Home",
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_TOKEN,
                        CONF_USERNAME: username,
                        CONF_MASTER_TOKEN: master_token,
                    },
                )

        return self.async_show_form(
            step_id="token",
            data_schema=data_schema,
            errors=self._errors,
        )

    async def async_step_app_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle App Password authentication with automatic token generation."""
        self._errors = {}
        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        if user_input is not None:
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "").strip()
            session = async_get_clientsession(self.hass)

            if len(password) > MAX_PASSWORD_LENGTH:
                self._errors["base"] = "password_too_long"
            else:
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=session,
                    username=username,
                    password=password,
                )
                try:
                    extracted_token = await client.get_master_token()
                except AdvancedProtectionActive:
                    self._errors["base"] = "advanced_protection"
                except TwoFactorRequired:
                    self._errors["base"] = "two_factor_required"
                except (AuthenticationFailed, InvalidMasterToken):
                    self._errors["base"] = "invalid_auth"
                except Exception as err:
                    _LOGGER.exception(
                        "Unexpected error during app password login: %s", err
                    )
                    self._errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(DOMAIN)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Google Home",
                        data={
                            CONF_AUTH_METHOD: AUTH_METHOD_CREDENTIALS,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_MASTER_TOKEN: extracted_token,
                        },
                    )

        return self.async_show_form(
            step_id="app_password",
            data_schema=data_schema,
            errors=self._errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get options flow handler."""
        return GoogleHomeOptionsFlowHandler()


class GoogleHomeOptionsFlowHandler(OptionsFlow):
    """Handle Google Home options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Google Home options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=current_interval): vol.All(
                    vol.Coerce(int), vol.Clamp(min=10, max=600)
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )
