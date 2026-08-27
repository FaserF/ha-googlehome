"""Config flow for Google Home integration."""

from __future__ import annotations

import asyncio
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
    AUTH_METHOD_TOKEN,
    CONF_ADDON_HOST,
    CONF_ADDON_PORT,
    CONF_AUTH_METHOD,
    CONF_CLOUD_UPDATE_INTERVAL,
    CONF_IGNORE_HA_SYNCED_DEVICES,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    CONF_SELECTED_HOMES,
    CONF_THIRD_PARTY_ENTITY_MODE,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_CLOUD_CLIENT,
    DATA_CLOUD_COORDINATOR,
    DEFAULT_ADDON_HOST,
    DEFAULT_ADDON_PORT,
    DEFAULT_CLOUD_UPDATE_INTERVAL,
    DEFAULT_IGNORE_HA_SYNCED_DEVICES,
    DEFAULT_LOCAL_UPDATE_INTERVAL,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    MODE_CLOUD,
    MODE_HYBRID,
    MODE_LOCAL,
    THIRD_PARTY_MODE_ASSISTANT_SDK,
    THIRD_PARTY_MODE_DIRECT_CLOUD,
    THIRD_PARTY_MODE_READONLY,
)
from .exceptions import (
    AuthenticationFailed,
    InvalidMasterToken,
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
                "setup_url": "https://accounts.google.com/EmbeddedSetup",
                "cookies_url": "https://accounts.google.com",
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

        return self.async_show_form(
            step_id="mode",
            data_schema=vol.Schema(schema_dict),
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
            selected_third_party_mode = user_input.get(
                CONF_THIRD_PARTY_ENTITY_MODE, DEFAULT_THIRD_PARTY_ENTITY_MODE
            )
            if selected_third_party_mode == THIRD_PARTY_MODE_ASSISTANT_SDK:
                has_assistant_sdk = self.hass.services.has_service(
                    "google_assistant_sdk", "send_text_command"
                )
                if not has_assistant_sdk:
                    errors["base"] = "assistant_sdk_missing"

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
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
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

        has_assistant_sdk = self.hass.services.has_service(
            "google_assistant_sdk", "send_text_command"
        )
        default_fallback_mode = (
            THIRD_PARTY_MODE_ASSISTANT_SDK
            if has_assistant_sdk
            else THIRD_PARTY_MODE_READONLY
        )
        current_third_party_mode = self.config_entry.options.get(
            CONF_THIRD_PARTY_ENTITY_MODE,
            self.config_entry.data.get(
                CONF_THIRD_PARTY_ENTITY_MODE, default_fallback_mode
            ),
        )

        third_party_mode_options = [
            SelectOptionDict(
                value=THIRD_PARTY_MODE_READONLY,
                label="Read-Only Sensors (Default - Live telemetry without duplicate control entities)",
            ),
            SelectOptionDict(
                value=THIRD_PARTY_MODE_DIRECT_CLOUD,
                label="Control Entities without Execution (Light/Fan/Switch/Nightlight entities, direct cloud sync)",
            ),
            SelectOptionDict(
                value=THIRD_PARTY_MODE_ASSISTANT_SDK,
                label="Control Entities with Google Assistant SDK Execution (Universal text command forwarding via official Google Assistant SDK)",
            ),
        ]

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_OPERATION_MODE, default=current_mode): SelectSelector(
                SelectSelectorConfig(
                    options=[MODE_HYBRID, MODE_LOCAL, MODE_CLOUD],
                    translation_key="operation_mode",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_THIRD_PARTY_ENTITY_MODE, default=current_third_party_mode
            ): SelectSelector(
                SelectSelectorConfig(
                    options=third_party_mode_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        if homes_options:
            all_hids = [opt["value"] for opt in homes_options]
            default_selection = current_homes if current_homes is not None else all_hids
            schema_dict[
                vol.Optional(CONF_SELECTED_HOMES, default=default_selection)
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=homes_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )

        current_local_interval = self.config_entry.options.get(
            CONF_LOCAL_UPDATE_INTERVAL,
            self.config_entry.data.get(
                CONF_LOCAL_UPDATE_INTERVAL,
                DEFAULT_LOCAL_UPDATE_INTERVAL,
            ),
        )
        current_cloud_interval = self.config_entry.options.get(
            CONF_CLOUD_UPDATE_INTERVAL,
            self.config_entry.data.get(
                CONF_CLOUD_UPDATE_INTERVAL,
                DEFAULT_CLOUD_UPDATE_INTERVAL,
            ),
        )

        schema_dict.update(
            {
                vol.Required(
                    CONF_IGNORE_HA_SYNCED_DEVICES, default=current_ignore_ha
                ): BooleanSelector(),
                vol.Required(
                    CONF_LOCAL_UPDATE_INTERVAL,
                    default=max(60, int(current_local_interval)),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=60,
                        max=3600,
                        step=5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Required(
                    CONF_CLOUD_UPDATE_INTERVAL,
                    default=max(60, int(current_cloud_interval)),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=60,
                        max=3600,
                        step=10,
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
