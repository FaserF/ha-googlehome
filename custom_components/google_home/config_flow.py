"""Config flow for Google Home integration."""

from __future__ import annotations

import logging
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
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .addon_flow import AddonFlowMixin
from .api import GlocaltokensApiClient
from .const import (
    ADDON_CONTAINER_HOSTS,
    AUTH_METHOD_ADDON,
    AUTH_METHOD_APP_PASSWORD,
    AUTH_METHOD_TOKEN,
    CONF_ADDON_HOST,
    CONF_ADDON_PORT,
    CONF_AUTH_METHOD,
    CONF_IGNORE_HA_SYNCED_DEVICES,
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    CONF_PASSWORD,
    CONF_SELECTED_HOMES,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DEFAULT_ADDON_HOST,
    DEFAULT_ADDON_PORT,
    DEFAULT_IGNORE_HA_SYNCED_DEVICES,
    DEFAULT_UPDATE_INTERVAL,
    DATA_CLIENT,
    DATA_CLOUD_CLIENT,
    DATA_CLOUD_COORDINATOR,
    DATA_COORDINATOR,
    DOMAIN,
    MAX_PASSWORD_LENGTH,
    MODE_CLOUD,
    MODE_HYBRID,
    MODE_LOCAL,
)
from .exceptions import (
    AdvancedProtectionActive,
    AuthenticationFailed,
    InvalidMasterToken,
    TwoFactorRequired,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeFlowHandler(AddonFlowMixin, ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Google Home."""

    VERSION = 3

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
        self._discovery_source = "hassio"
        host = discovery_info.config.get("host", DEFAULT_ADDON_HOST)
        port = int(discovery_info.config.get("port", DEFAULT_ADDON_PORT))
        return await self._async_connect_addon(host, port)

    async def async_step_zeroconf(self, discovery_info: Any) -> ConfigFlowResult:
        """Handle zeroconf discovery of Google Cast / Home devices."""
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
                vol.Required(
                    CONF_AUTH_METHOD, default=AUTH_METHOD_TOKEN
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            AUTH_METHOD_TOKEN,
                            AUTH_METHOD_ADDON,
                            AUTH_METHOD_APP_PASSWORD,
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
            },
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
        )

    async def async_step_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step to select operation mode (Local & Cloud, Local only, Cloud only), home selection, and HA entity filtering."""
        if user_input is not None:
            mode = user_input.get(CONF_OPERATION_MODE, MODE_HYBRID)
            ignore_ha = user_input.get(
                CONF_IGNORE_HA_SYNCED_DEVICES, DEFAULT_IGNORE_HA_SYNCED_DEVICES
            )
            selected_homes = user_input.get(CONF_SELECTED_HOMES)

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
                    CONF_IGNORE_HA_SYNCED_DEVICES: ignore_ha,
                    CONF_SELECTED_HOMES: selected_homes,
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

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_OPERATION_MODE, default=MODE_HYBRID): SelectSelector(
                SelectSelectorConfig(
                    options=[MODE_HYBRID, MODE_LOCAL, MODE_CLOUD],
                    translation_key="operation_mode",
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

        return self.async_show_form(
            step_id="mode",
            data_schema=vol.Schema(schema_dict),
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

            if not username or "@" not in username or "." not in username:
                self._errors["base"] = "invalid_email"
            elif not password:
                self._errors["base"] = "missing_credentials"
            elif len(password) > MAX_PASSWORD_LENGTH:
                self._errors["base"] = "password_too_long"
            else:
                clean_pwd = (
                    password.replace(" ", "")
                    if len(password.replace(" ", "")) == 16
                    else password
                )
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=session,
                    username=username,
                    password=clean_pwd,
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
                    self._master_token = extracted_token
                    self._username = username
                    return await self.async_step_mode()

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
        errors: dict[str, str] = {}

        if user_input is not None:
            new_token = user_input.get(CONF_MASTER_TOKEN, "").strip()
            username = self.config_entry.data.get(CONF_USERNAME, "")
            session = async_get_clientsession(self.hass)

            # If user entered an oauth2_4 web token, exchange it automatically
            if new_token and (
                new_token.startswith("oauth2_4/") or new_token.startswith("1//")
            ):
                try:
                    client = GlocaltokensApiClient(
                        hass=self.hass,
                        session=session,
                        username=username,
                    )
                    exchanged = await client.exchange_web_token(new_token)
                    user_input[CONF_MASTER_TOKEN] = exchanged
                except Exception as err:
                    _LOGGER.error("Failed to exchange new web token: %s", err)
                    errors["base"] = "invalid_token"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current_token = self.config_entry.options.get(
            CONF_MASTER_TOKEN,
            self.config_entry.data.get(CONF_MASTER_TOKEN, ""),
        )
        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        current_mode = self.config_entry.options.get(
            CONF_OPERATION_MODE,
            self.config_entry.data.get(CONF_OPERATION_MODE, MODE_HYBRID),
        )
        current_ignore_ha = self.config_entry.options.get(
            CONF_IGNORE_HA_SYNCED_DEVICES,
            self.config_entry.data.get(
                CONF_IGNORE_HA_SYNCED_DEVICES, DEFAULT_IGNORE_HA_SYNCED_DEVICES
            ),
        )

        current_homes = self.config_entry.options.get(
            CONF_SELECTED_HOMES,
            self.config_entry.data.get(CONF_SELECTED_HOMES),
        )

        # Query available homes for multi-selection
        homes_dict: dict[str, str] = {}
        entry_data = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id, {}
        )
        cloud_coord = entry_data.get(DATA_CLOUD_COORDINATOR)
        cloud_client = entry_data.get(DATA_CLOUD_CLIENT)
        local_client = entry_data.get(DATA_CLIENT)

        # 1. From active cloud coordinator data
        if cloud_coord and cloud_coord.data:
            for dev in cloud_coord.data:
                if dev.structure_id and dev.structure_name:
                    homes_dict[dev.structure_id] = dev.structure_name

        # 2. From active cloud client
        if cloud_client and hasattr(cloud_client, "_get_available_homes_sync"):
            try:
                homes_dict.update(cloud_client._get_available_homes_sync())
            except Exception as err:
                _LOGGER.debug("Could not query homes from cloud client: %s", err)

        # 3. From active local client
        if local_client:
            try:
                homes_dict.update(await local_client.async_get_available_homes())
            except Exception as err:
                _LOGGER.debug("Could not query homes from local client: %s", err)

        # 4. Fallback if integration not loaded but token present
        if not homes_dict and current_token:
            try:
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=session,
                    username=username,
                    master_token=current_token,
                )
                homes_dict.update(await client.async_get_available_homes())
            except Exception as err:
                _LOGGER.debug("Could not query homes in options flow: %s", err)

        homes_options: list[SelectOptionDict] = [
            SelectOptionDict(value=hid, label=hname)
            for hid, hname in homes_dict.items()
        ]

        # Ensure any currently configured homes are included as options
        if current_homes and isinstance(current_homes, list):
            existing_values = {opt["value"] for opt in homes_options}
            for ch in current_homes:
                if ch not in existing_values:
                    homes_options.append(SelectOptionDict(value=ch, label=ch))

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_OPERATION_MODE, default=current_mode): SelectSelector(
                SelectSelectorConfig(
                    options=[MODE_HYBRID, MODE_LOCAL, MODE_CLOUD],
                    translation_key="operation_mode",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        if homes_options:
            all_hids = [opt["value"] for opt in homes_options]
            default_selection = (
                current_homes if current_homes is not None else all_hids
            )
            schema_dict[
                vol.Optional(CONF_SELECTED_HOMES, default=default_selection)
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=homes_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )

        schema_dict.update(
            {
                vol.Required(
                    CONF_IGNORE_HA_SYNCED_DEVICES, default=current_ignore_ha
                ): BooleanSelector(),
                vol.Required(
                    CONF_UPDATE_INTERVAL, default=current_interval
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=10,
                        max=600,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(CONF_MASTER_TOKEN, default=current_token): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="current-password",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
