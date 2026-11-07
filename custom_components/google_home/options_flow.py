"""Options flow for Google Home integration."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]
from homeassistant.config_entries import (
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant
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

from .api import GlocaltokensApiClient
from .cloud_api import GoogleHomeCloudClient
from .const import (
    CONF_BLUETOOTH_EXCLUDED,
    CONF_BLUETOOTH_TRACKING,
    CONF_CLOUD_UPDATE_INTERVAL,
    CONF_EXCLUDED_SERVICES,
    CONF_IGNORE_HA_SYNCED_DEVICES,
    CONF_KNOWN_HOSTS,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MASTER_TOKEN,
    CONF_MUTE_SDK_NIGHTLIGHT,
    CONF_OPERATION_MODE,
    CONF_SELECTED_HOMES,
    CONF_THIRD_PARTY_ENTITY_MODE,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_CLOUD_CLIENT,
    DATA_CLOUD_COORDINATOR,
    DATA_COORDINATOR,
    DEFAULT_CLOUD_UPDATE_INTERVAL,
    DEFAULT_IGNORE_HA_SYNCED_DEVICES,
    DEFAULT_LOCAL_UPDATE_INTERVAL,
    DEFAULT_MUTE_SDK_NIGHTLIGHT,
    DEFAULT_THIRD_PARTY_ENTITY_MODE,
    DOMAIN,
    MIN_LOCAL_UPDATE_INTERVAL,
    MODE_CLOUD,
    MODE_HYBRID,
    MODE_LOCAL,
    THIRD_PARTY_MODE_ASSISTANT_SDK,
    THIRD_PARTY_MODE_DIRECT_CLOUD,
    THIRD_PARTY_MODE_READONLY,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def _async_service_options(
    hass: HomeAssistant,
    username: str | None,
    master_token: str | None,
    excluded_services: list[str],
    client: GoogleHomeCloudClient | None = None,
) -> list[SelectOptionDict]:
    """Offer unfiltered provider IDs and keep saved exclusions selectable on failure."""
    services: dict[str, str] = {}
    if client is not None or master_token:
        try:
            if client is None:
                client = GoogleHomeCloudClient(
                    hass=hass, username=username, master_token=master_token or ""
                )
            services = await client.async_get_available_services()
        except Exception as err:
            _LOGGER.debug("Could not discover linked services: %s", err)
    for service_id in excluded_services:
        services.setdefault(service_id, service_id)
    return [
        SelectOptionDict(
            value=service_id,
            label=(
                f"{name} ({service_id})"
                if list(services.values()).count(name) > 1
                else name
            ),
        )
        for service_id, name in sorted(
            services.items(), key=lambda item: (item[1].casefold(), item[0])
        )
    ]


def _is_ip_address(host: str) -> bool:
    """Return whether a known host is an IP address."""
    try:
        ipaddress.ip_address(host.strip())
    except ValueError:
        return False
    return True


class GoogleHomeOptionsFlowHandler(OptionsFlow):
    """Handle Google Home options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Google Home options."""
        errors: dict[str, str] = {}
        username = self.config_entry.data.get(CONF_USERNAME, "")
        session = async_get_clientsession(self.hass)

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

            raw_known_hosts = user_input.get(CONF_KNOWN_HOSTS, [])
            if isinstance(raw_known_hosts, list):
                cleaned_hosts: list[str] = []
                for host in raw_known_hosts:
                    if isinstance(host, str):
                        h = host.strip()
                        if h and h not in cleaned_hosts:
                            cleaned_hosts.append(h)
                if not all(_is_ip_address(h) for h in cleaned_hosts):
                    errors[CONF_KNOWN_HOSTS] = "known-host-not-ip"
                else:
                    user_input[CONF_KNOWN_HOSTS] = cleaned_hosts

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
                user_input.setdefault(CONF_EXCLUDED_SERVICES, [])
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
        current_mute_sdk_nightlight = self.config_entry.options.get(
            CONF_MUTE_SDK_NIGHTLIGHT,
            self.config_entry.data.get(
                CONF_MUTE_SDK_NIGHTLIGHT, DEFAULT_MUTE_SDK_NIGHTLIGHT
            ),
        )

        current_homes = self.config_entry.options.get(
            CONF_SELECTED_HOMES,
            self.config_entry.data.get(CONF_SELECTED_HOMES),
        )
        current_bluetooth_tracking = self.config_entry.options.get(
            CONF_BLUETOOTH_TRACKING, False
        )
        current_bluetooth_excluded = self.config_entry.options.get(
            CONF_BLUETOOTH_EXCLUDED, []
        )
        speaker_options: list[SelectOptionDict] = []
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        local_coord = entry_data.get(DATA_COORDINATOR)
        if local_coord and local_coord.data:
            for dev in local_coord.data:
                speaker_options.append(
                    SelectOptionDict(
                        value=dev.device_id, label=dev.name or dev.device_id
                    )
                )

        # Query available homes for multi-selection
        homes_dict: dict[str, str] = {}
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        cloud_coord = entry_data.get(DATA_CLOUD_COORDINATOR)
        cloud_client = entry_data.get(DATA_CLOUD_CLIENT)
        local_client = entry_data.get(DATA_CLIENT)
        current_excluded = self.config_entry.options.get(
            CONF_EXCLUDED_SERVICES,
            self.config_entry.data.get(CONF_EXCLUDED_SERVICES, []),
        )
        service_options = await _async_service_options(
            self.hass, username, current_token, current_excluded, cloud_client
        )

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

        # Group IDs by home name so user sees each home once
        name_to_ids: dict[str, list[str]] = {}
        for hid, hname in homes_dict.items():
            name_to_ids.setdefault(hname, []).append(hid)

        homes_options: list[SelectOptionDict] = []
        for hname, _ids in name_to_ids.items():
            # Use the home name itself (or primary ID) as canonical value
            homes_options.append(SelectOptionDict(value=hname, label=hname))

        # Ensure any currently configured homes are included as options (supporting both legacy ID and name)
        if current_homes and isinstance(current_homes, list):
            existing_values = {opt["value"] for opt in homes_options}
            normalized_current_homes: list[str] = []
            for ch in current_homes:
                if not ch:
                    continue
                matched_name = str(homes_dict.get(ch, ch))
                if matched_name not in normalized_current_homes:
                    normalized_current_homes.append(matched_name)
                if matched_name not in existing_values:
                    homes_options.append(
                        SelectOptionDict(value=matched_name, label=matched_name)
                    )
                    existing_values.add(matched_name)
            current_homes = normalized_current_homes

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
            vol.Optional(
                CONF_EXCLUDED_SERVICES, default=current_excluded
            ): SelectSelector(
                SelectSelectorConfig(
                    options=service_options, multiple=True, mode=SelectSelectorMode.LIST
                )
            ),
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
                    CONF_MUTE_SDK_NIGHTLIGHT, default=current_mute_sdk_nightlight
                ): BooleanSelector(),
                vol.Required(
                    CONF_LOCAL_UPDATE_INTERVAL,
                    default=max(MIN_LOCAL_UPDATE_INTERVAL, int(current_local_interval)),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_LOCAL_UPDATE_INTERVAL,
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
                vol.Optional(
                    CONF_BLUETOOTH_TRACKING, default=current_bluetooth_tracking
                ): BooleanSelector(),
            }
        )

        if speaker_options:
            schema_dict[
                vol.Optional(
                    CONF_BLUETOOTH_EXCLUDED, default=current_bluetooth_excluded
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=speaker_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )

        current_known_hosts = self.config_entry.options.get(
            CONF_KNOWN_HOSTS,
            self.config_entry.data.get(CONF_KNOWN_HOSTS, []),
        )
        if not isinstance(current_known_hosts, list):
            current_known_hosts = []

        schema_dict[vol.Optional(CONF_KNOWN_HOSTS, default=current_known_hosts)] = (
            SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=h, label=h) for h in current_known_hosts
                    ],
                    custom_value=True,
                    multiple=True,
                )
            )
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
