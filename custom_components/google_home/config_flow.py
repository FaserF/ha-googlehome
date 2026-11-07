"""Config flow for Google Home integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .addon_flow import AddonFlowMixin
from .api import GlocaltokensApiClient
from .const import (
    ADDON_CONTAINER_HOSTS,
    AUTH_METHOD_ADDON,
    AUTH_METHOD_TOKEN,
    CONF_ADDON_HOST,
    CONF_ADDON_PORT,
    CONF_AUTH_METHOD,
    CONF_EXCLUDED_SERVICES,
    CONF_IGNORE_HA_SYNCED_DEVICES,
    CONF_MASTER_TOKEN,
    CONF_MUTE_SDK_NIGHTLIGHT,
    CONF_OPERATION_MODE,
    CONF_SELECTED_HOMES,
    CONF_THIRD_PARTY_ENTITY_MODE,
    CONF_USERNAME,
    DEFAULT_ADDON_HOST,
    DEFAULT_ADDON_PORT,
    DEFAULT_IGNORE_HA_SYNCED_DEVICES,
    DEFAULT_MUTE_SDK_NIGHTLIGHT,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    MODE_CLOUD,
    MODE_HYBRID,
    MODE_LOCAL,
    SUBENTRY_BLUETOOTH_DEVICE,
    THIRD_PARTY_MODE_ASSISTANT_SDK,
    THIRD_PARTY_MODE_DIRECT_CLOUD,
    THIRD_PARTY_MODE_READONLY,
)
from .exceptions import (
    AuthenticationFailed,
    InvalidMasterToken,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


from .options_flow import GoogleHomeOptionsFlowHandler, _async_service_options
from .reauth_flow import ReauthFlowMixin
from .subentry_flow import BluetoothDeviceSubentryFlow


class GoogleHomeFlowHandler(ConfigFlow, AddonFlowMixin, ReauthFlowMixin, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Google Home."""

    VERSION = 3

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentries this integration supports."""
        return {SUBENTRY_BLUETOOTH_DEVICE: BluetoothDeviceSubentryFlow}

    def __init__(self) -> None:
        """Initialize."""
        self._username: str | None = None
        self._master_token: str | None = None
        self._addon_host: str = DEFAULT_ADDON_HOST
        self._addon_port: int = DEFAULT_ADDON_PORT
        self._errors: dict[str, str] = {}
        self._discovered_device_name: str | None = None
        self._discovery_source: str = "manual"

    async def _async_probe_addon(self) -> tuple[str | None, dict[str, Any] | None]:
        """Probe potential add-on hosts (stable, edge, local) concurrently to find active addon instantly."""
        session = async_get_clientsession(self.hass)

        async def _check_host(host: str) -> tuple[str, dict[str, Any]] | None:
            url = f"http://{host}:{DEFAULT_ADDON_PORT}/api/v1/session"
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=0.5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return host, data
            except Exception:
                pass
            return None

        results = await asyncio.gather(
            *[_check_host(h) for h in ADDON_CONTAINER_HOSTS], return_exceptions=True
        )
        for res in results:
            if isinstance(res, tuple) and res is not None:
                return res
        return None, None

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle Home Assistant Supervisor auto-discovery from googlehome add-on."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        _LOGGER.info(
            "Supervisor auto-discovered Google Home Add-on: %s", discovery_info
        )
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        self._discovery_source = "hassio"
        host = discovery_info.config.get("host", DEFAULT_ADDON_HOST)
        port = int(discovery_info.config.get("port", DEFAULT_ADDON_PORT))
        return await self._async_connect_addon(host, port)

    async def async_step_zeroconf(self, discovery_info: Any) -> ConfigFlowResult:
        """Handle zeroconf discovery of Google Cast / Home devices."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        # Ensure only a single discovery flow / card is presented for the domain
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Abort if another discovery flow for google_home is already pending
        for progress in self._async_in_progress(include_uninitialized=True):
            if progress.get("flow_id") != self.flow_id:
                return self.async_abort(reason="already_in_progress")

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

        self._discovered_device_name = device_name
        self.context["title_placeholders"] = {"name": device_name}

        # Check if the Google Home Token Hub Add-on is running on the system
        found_host, _ = await self._async_probe_addon()
        if found_host:
            _LOGGER.info(
                "Zeroconf discovered %s and detected active Google Home Add-on at %s",
                device_name,
                found_host,
            )
            self._discovery_source = "zeroconf_with_addon"
            return await self._async_connect_addon(found_host, DEFAULT_ADDON_PORT)

        self._discovery_source = "zeroconf_only"
        return await self.async_step_user()

    def _async_abort_discovery_flows(self) -> None:
        """Abort any in-progress discovery flows (zeroconf/hassio) that are NOT this flow.

        This allows the user to always start a fresh manual flow even when a
        discovery-triggered flow is stuck in progress (e.g. user cancelled zeroconf
        setup mid-way but HA still has the flow in its queue).
        """
        current_flow_id = self.flow_id
        for progress in self._async_in_progress(include_uninitialized=True):
            flow_id = progress.get("flow_id")
            if flow_id and flow_id != current_flow_id:
                source = progress.get("context", {}).get("source", "")
                if source in ("zeroconf", "hassio", "discovery", "ssdp", "mqtt"):
                    _LOGGER.debug(
                        "Aborting stale %s discovery flow %s to allow manual setup",
                        source,
                        flow_id,
                    )
                    self.hass.config_entries.flow.async_abort(flow_id)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step: select authentication method."""
        self._errors = {}

        # Abort any lingering discovery flows so the user can always proceed manually.
        if self.source == "user":
            self._async_abort_discovery_flows()

        addon_info_hint = ""
        found_host, addon_session = await self._async_probe_addon()

        # If an active master token was already generated in the addon, offer 1-click adoption
        if user_input is None and not self._master_token:
            if (
                found_host
                and addon_session
                and addon_session.get("master_token")
                and addon_session.get("email")
            ):
                _LOGGER.info(
                    "Detected active Google Home Token Hub session for %s at %s - offering 1-click adoption",
                    addon_session.get("email"),
                    found_host,
                )
                self._addon_host = found_host
                self._username = addon_session.get("email")
                self._master_token = addon_session.get("master_token")
                return await self.async_step_addon_existing()

        if found_host:
            addon_info_hint = (
                "ℹ️ **Google Home Token Hub Add-on detected** (running without active token yet).\n"
                "- Open the [Google Home Token Hub Add-on UI](/hassio/ingress/googlehome) to generate your Master Token with 2FA support.\n\n"
            )
        else:
            addon_info_hint = (
                "💡 **Tip**: You can use the [Google Home Token Hub Add-on](https://github.com/FaserF/hassio-addons/tree/master/googlehome) "
                "to easily generate your token and 2FA keys directly inside Home Assistant, or proceed manually with a token below.\n\n"
            )

        if user_input is not None:
            method = user_input.get(CONF_AUTH_METHOD, AUTH_METHOD_TOKEN)
            if method == AUTH_METHOD_TOKEN:
                return await self.async_step_token()
            if method == AUTH_METHOD_ADDON:
                return await self.async_step_addon()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_AUTH_METHOD, default=AUTH_METHOD_TOKEN
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            AUTH_METHOD_TOKEN,
                            AUTH_METHOD_ADDON,
                        ],
                        translation_key="auth_method",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        discovery_intro = ""
        if self._discovery_source == "zeroconf_only":
            discovery_intro = f"🎉 Discovered **{self._discovered_device_name or 'Google Home'}** on your local network!\n\n"

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=self._errors,
            description_placeholders={
                "discovery_intro": discovery_intro,
                "addon_info_hint": addon_info_hint,
                "setup_url": "https://accounts.google.com/EmbeddedSetup",
                "cookies_url": "https://accounts.google.com",
            },
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Token authentication (Master Token or Web OAuth Token)."""
        self._errors = {}

        # If not already probed, check if add-on has token available for pre-filling
        if not self._master_token:
            found_host, addon_session = await self._async_probe_addon()
            if found_host and addon_session and addon_session.get("master_token"):
                self._master_token = addon_session.get("master_token")
                if not self._username and addon_session.get("email"):
                    self._username = addon_session.get("email")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=self._username or ""): str,
                vol.Required(CONF_MASTER_TOKEN, default=self._master_token or ""): str,
            }
        )

        if user_input is not None:
            username = user_input.get(CONF_USERNAME, "").strip()
            master_token = user_input.get(CONF_MASTER_TOKEN, "").strip()

            if not username or "@" not in username:
                self._errors["base"] = "invalid_email"
            elif not master_token:
                self._errors["base"] = "missing_credentials"
            else:
                session = async_get_clientsession(self.hass)
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=session,
                    username=username,
                    master_token=master_token,
                )
                try:
                    # If user provided a web OAuth token (oauth2_4/... or 1//...), exchange it
                    if master_token.startswith("oauth2_4/") or master_token.startswith(
                        "1//"
                    ):
                        master_token = await client.exchange_web_token(master_token)
                        client.master_token = master_token
                        client._client.master_token = master_token

                    # Validate token by retrieving access token
                    await client.get_access_token()
                except AuthenticationFailed:
                    self._errors["base"] = "invalid_master_token"
                except InvalidMasterToken:
                    self._errors["base"] = "invalid_master_token"
                except Exception as err:
                    _LOGGER.exception("Unexpected error validating token: %s", err)
                    self._errors["base"] = "unknown"
                else:
                    self._master_token = master_token
                    self._username = username
                    return await self.async_step_mode()

        return self.async_show_form(
            step_id="token",
            data_schema=data_schema,
            errors=self._errors,
            description_placeholders={
                "setup_url": "https://accounts.google.com/EmbeddedSetup",
                "cookies_url": "https://accounts.google.com",
            },
        )

    async def async_step_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step to select operation mode (Local & Cloud, Local only, Cloud only), home selection, and HA entity filtering."""
        if user_input is not None:
            mode = user_input.get(CONF_OPERATION_MODE, MODE_HYBRID)
            third_party_mode = user_input.get(
                CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
            )
            ignore_ha = user_input.get(
                CONF_IGNORE_HA_SYNCED_DEVICES, DEFAULT_IGNORE_HA_SYNCED_DEVICES
            )
            selected_homes = user_input.get(CONF_SELECTED_HOMES)
            mute_sdk_nightlight = user_input.get(
                CONF_MUTE_SDK_NIGHTLIGHT, DEFAULT_MUTE_SDK_NIGHTLIGHT
            )

            # Use normalized Google Account email as unique_id to allow multiple distinct accounts
            # while preventing duplicates of the same account
            account_unique_id = (
                self._username.strip().lower()
                if self._username
                else (self._master_token[:32] if self._master_token else DOMAIN)
            )
            await self.async_set_unique_id(account_unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Google Home ({self._username})"
                if self._username
                else "Google Home",
                data={
                    CONF_AUTH_METHOD: AUTH_METHOD_TOKEN,
                    CONF_USERNAME: self._username,
                    CONF_MASTER_TOKEN: self._master_token,
                    CONF_OPERATION_MODE: mode,
                    CONF_THIRD_PARTY_ENTITY_MODE: third_party_mode,
                    CONF_MUTE_SDK_NIGHTLIGHT: mute_sdk_nightlight,
                    CONF_IGNORE_HA_SYNCED_DEVICES: ignore_ha,
                    CONF_SELECTED_HOMES: selected_homes,
                    CONF_EXCLUDED_SERVICES: user_input.get(CONF_EXCLUDED_SERVICES, []),
                    CONF_ADDON_HOST: self._addon_host,
                    CONF_ADDON_PORT: self._addon_port,
                },
            )

        # Query available Google Homes for multi-select
        homes_options: list[SelectOptionDict] = []
        if self._master_token:
            try:
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=async_get_clientsession(self.hass),
                    username=self._username,
                    master_token=self._master_token,
                )
                homes_dict = await client.async_get_available_homes()
                for hid, hname in homes_dict.items():
                    homes_options.append(SelectOptionDict(value=hid, label=hname))
            except Exception as err:
                _LOGGER.debug("Could not query homes during config flow: %s", err)

        service_options = await _async_service_options(
            self.hass, self._username, self._master_token, []
        )

        has_assistant_sdk = self.hass.services.has_service(
            "google_assistant_sdk", "send_text_command"
        )
        default_third_party_mode = (
            THIRD_PARTY_MODE_ASSISTANT_SDK
            if has_assistant_sdk
            else THIRD_PARTY_MODE_READONLY
        )
        initial_third_party_options = [
            THIRD_PARTY_MODE_READONLY,
            THIRD_PARTY_MODE_DIRECT_CLOUD,
        ]
        if has_assistant_sdk:
            initial_third_party_options.append(THIRD_PARTY_MODE_ASSISTANT_SDK)

        schema_dict: dict[Any, Any] = {
            vol.Optional(CONF_EXCLUDED_SERVICES, default=[]): SelectSelector(
                SelectSelectorConfig(
                    options=service_options, multiple=True, mode=SelectSelectorMode.LIST
                )
            ),
            vol.Required(CONF_OPERATION_MODE, default=MODE_HYBRID): SelectSelector(
                SelectSelectorConfig(
                    options=[MODE_HYBRID, MODE_LOCAL, MODE_CLOUD],
                    translation_key="operation_mode",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_THIRD_PARTY_ENTITY_MODE, default=default_third_party_mode
            ): SelectSelector(
                SelectSelectorConfig(
                    options=initial_third_party_options,
                    translation_key="third_party_entity_mode",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        if homes_options:
            all_home_ids = [opt["value"] for opt in homes_options]
            schema_dict[vol.Optional(CONF_SELECTED_HOMES, default=all_home_ids)] = (
                SelectSelector(
                    SelectSelectorConfig(
                        options=homes_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            )

        schema_dict[
            vol.Required(
                CONF_IGNORE_HA_SYNCED_DEVICES,
                default=DEFAULT_IGNORE_HA_SYNCED_DEVICES,
            )
        ] = BooleanSelector()
        schema_dict[
            vol.Required(
                CONF_MUTE_SDK_NIGHTLIGHT,
                default=DEFAULT_MUTE_SDK_NIGHTLIGHT,
            )
        ] = BooleanSelector()

        return self.async_show_form(
            step_id="mode",
            data_schema=vol.Schema(schema_dict),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get options flow handler."""
        return GoogleHomeOptionsFlowHandler()
