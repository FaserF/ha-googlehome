"""The Google Home component."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GlocaltokensApiClient
from .cleanup import _async_cleanup_stale_devices_and_entities
from .const import (
    CONF_ANDROID_ID,
    CONF_BLUETOOTH_EXCLUDED,
    CONF_BLUETOOTH_TRACKING,
    CONF_CLOUD_UPDATE_INTERVAL,
    CONF_EXCLUDED_SERVICES,
    CONF_IGNORE_HA_SYNCED_DEVICES,
    CONF_KNOWN_HOSTS,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MASTER_TOKEN,
    CONF_OPERATION_MODE,
    CONF_PASSWORD,
    CONF_SELECTED_HOMES,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_CLOUD_CLIENT,
    DATA_CLOUD_COORDINATOR,
    DATA_COORDINATOR,
    DEFAULT_CLOUD_UPDATE_INTERVAL,
    DEFAULT_IGNORE_HA_SYNCED_DEVICES,
    DEFAULT_LOCAL_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ISSUE_INVALID_INTERVAL,
    ISSUE_POLLING_DISABLED,
    MIN_LOCAL_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    MODE_CLOUD,
    MODE_HYBRID,
    MODE_LOCAL,
    PLATFORMS,
    SUBENTRY_BLUETOOTH_DEVICE,
    UPDATE_INTERVAL,
)
from .coordinator import GoogleHomeDataUpdateCoordinator
from .exceptions import AuthenticationFailed, InvalidMasterToken, TwoFactorRequired
from .migration import async_migrate_entry
from .registry_repair import async_repair_placeholder_macs

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Google Home from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    async_show_polling_disabled(hass, entry)
    async_show_invalid_interval(hass, entry)

    # Suppress noisy ERROR-level messages from the glocaltokens library when
    # the master token is invalid/expired - these are expected auth failures
    # that are already handled by our AuthenticationFailed exception path.
    logging.getLogger("glocaltokens").setLevel(logging.CRITICAL)

    username = cast("str | None", entry.data.get(CONF_USERNAME))
    password = cast("str | None", entry.data.get(CONF_PASSWORD))
    master_token = cast(
        "str | None",
        entry.options.get(CONF_MASTER_TOKEN, entry.data.get(CONF_MASTER_TOKEN)),
    )
    android_id = cast("str | None", entry.data.get(CONF_ANDROID_ID))

    mode = entry.options.get(
        CONF_OPERATION_MODE,
        entry.data.get(CONF_OPERATION_MODE, MODE_HYBRID),
    )
    ignore_ha_synced = entry.options.get(
        CONF_IGNORE_HA_SYNCED_DEVICES,
        entry.data.get(CONF_IGNORE_HA_SYNCED_DEVICES, DEFAULT_IGNORE_HA_SYNCED_DEVICES),
    )
    selected_homes = entry.options.get(
        CONF_SELECTED_HOMES,
        entry.data.get(CONF_SELECTED_HOMES),
    )
    # Retrieve polling intervals: local (default 120s, min 60s), cloud (default 300s, min 60s)

    legacy_interval = entry.options.get(
        CONF_UPDATE_INTERVAL,
        entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
    )
    local_update_interval = entry.options.get(
        CONF_LOCAL_UPDATE_INTERVAL,
        entry.data.get(
            CONF_LOCAL_UPDATE_INTERVAL,
            legacy_interval if legacy_interval != 60 else DEFAULT_LOCAL_UPDATE_INTERVAL,
        ),
    )
    # Enforce minimum interval for local polling (min 5s for fast timer detection)
    local_update_interval = max(MIN_LOCAL_UPDATE_INTERVAL, int(local_update_interval))

    cloud_update_interval = entry.options.get(
        CONF_CLOUD_UPDATE_INTERVAL,
        entry.data.get(CONF_CLOUD_UPDATE_INTERVAL, DEFAULT_CLOUD_UPDATE_INTERVAL),
    )
    # Enforce minimum 60s for cloud polling
    cloud_update_interval = max(60, int(cloud_update_interval))

    session = async_get_clientsession(hass)

    entry_data: dict[str, Any] = {}
    hass.data[DOMAIN][entry.entry_id] = entry_data

    # 1. Setup Local Subsystem
    if mode in (MODE_HYBRID, MODE_LOCAL):
        zeroconf_instance = await zeroconf.async_get_instance(hass)
        known_hosts = entry.options.get(
            CONF_KNOWN_HOSTS,
            entry.data.get(CONF_KNOWN_HOSTS, []),
        )
        client = GlocaltokensApiClient(
            hass=hass,
            session=session,
            username=username,
            password=password,
            master_token=master_token,
            android_id=android_id,
            zeroconf_instance=zeroconf_instance,
            selected_homes=selected_homes,
            known_hosts=known_hosts if isinstance(known_hosts, list) else None,
        )
        coordinator = GoogleHomeDataUpdateCoordinator(
            hass=hass,
            client=client,
            update_interval=local_update_interval,
        )
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed:
            raise
        except (AuthenticationFailed, InvalidMasterToken, TwoFactorRequired) as err:
            raise ConfigEntryAuthFailed(
                f"Google Home authentication expired or invalid: {err}"
            ) from err
        except Exception as err:
            _LOGGER.warning("Initial local refresh warning: %s", err)

        entry_data[DATA_CLIENT] = client
        coordinator.config_entry = entry
        entry_data[DATA_COORDINATOR] = coordinator

    # 2. Setup Cloud Subsystem (initialize None to avoid UnboundLocalError in MODE_LOCAL; fixes #27)
    cloud_coordinator = None
    if mode in (MODE_HYBRID, MODE_CLOUD) and master_token:
        from .cloud_api import GoogleHomeCloudClient
        from .cloud_coordinator import GoogleHomeCloudDataUpdateCoordinator

        cloud_client = GoogleHomeCloudClient(
            hass=hass,
            master_token=master_token,
            username=username,
            android_id=android_id,
            ignore_ha_synced=ignore_ha_synced,
            selected_homes=selected_homes,
            excluded_services=entry.options.get(
                CONF_EXCLUDED_SERVICES, entry.data.get(CONF_EXCLUDED_SERVICES, [])
            ),
        )
        cloud_coordinator = GoogleHomeCloudDataUpdateCoordinator(
            hass=hass,
            client=cloud_client,
            update_interval=cloud_update_interval,
        )
        cloud_coordinator.config_entry = entry
        try:
            await cloud_coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed:
            raise
        except (AuthenticationFailed, InvalidMasterToken, TwoFactorRequired) as err:
            raise ConfigEntryAuthFailed(
                f"Google Home Cloud authentication expired or invalid: {err}"
            ) from err
        except Exception as err:
            _LOGGER.warning("Initial cloud refresh warning: %s", err)

        entry_data[DATA_CLOUD_CLIENT] = cloud_client
        entry_data[DATA_CLOUD_COORDINATOR] = cloud_coordinator
    # 0. Migrate legacy leikoilja entity unique_ids before setting up platforms
    # This ensures new platform entities match the existing registry entries and keep entity_ids & names
    ent_reg = er.async_get(hass)
    for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = ent_entry.unique_id or ""
        # Handle deprecated leikoilja device sensor (e.g. '<device_id>/device' or '<device_id>_device')
        if uid.endswith("/device") or uid.endswith("_device"):
            _LOGGER.info(
                "Removing deprecated legacy device sensor entity: %s (%s)",
                ent_entry.entity_id,
                uid,
            )
            ent_reg.async_remove(ent_entry.entity_id)
            continue

        # Map leikoilja unique_ids:
        # '<device_id>/alarms' -> '<device_id>_alarms'
        # '<device_id>/timers' -> '<device_id>_timers'
        # '<device_id>/alarm volume' or '<device_id>_alarm volume' -> '<device_id>_alarm_volume'
        # '<device_id>/Do Not Disturb' or '<device_id>_Do Not Disturb' -> '<device_id>_do_not_disturb'
        new_uid = uid.replace("/", "_")
        if new_uid.endswith("_alarm volume"):
            new_uid = new_uid.replace("_alarm volume", "_alarm_volume")
        elif new_uid.endswith("_Do Not Disturb") or new_uid.endswith("_do not disturb"):
            new_uid = new_uid.replace("_Do Not Disturb", "_do_not_disturb").replace(
                "_do not disturb", "_do_not_disturb"
            )

        if new_uid != uid:
            existing_new_ent = ent_reg.async_get_entity_id(
                ent_entry.domain, DOMAIN, new_uid
            )
            if existing_new_ent and existing_new_ent != ent_entry.entity_id:
                _LOGGER.info(
                    "Removing duplicate newer entity %s to restore migrated entity %s",
                    existing_new_ent,
                    ent_entry.entity_id,
                )
                ent_reg.async_remove(existing_new_ent)

            _LOGGER.info(
                "Migrating entity unique_id '%s' -> '%s' for %s",
                uid,
                new_uid,
                ent_entry.entity_id,
            )
            try:
                ent_reg.async_update_entity(ent_entry.entity_id, new_unique_id=new_uid)
            except Exception as err:
                _LOGGER.warning(
                    "Could not migrate entity unique_id for %s: %s",
                    ent_entry.entity_id,
                    err,
                )

    # Clean up stale fallback default_home presence tracker if real homes exist in cloud coordinator
    if cloud_coordinator and (
        cloud_coordinator.data
        or getattr(cloud_coordinator.client, "_cached_homes", None)
    ):
        stale_default_home_ent = ent_reg.async_get_entity_id(
            "device_tracker", DOMAIN, "google_home_presence_default_home"
        )
        if stale_default_home_ent:
            _LOGGER.info(
                "Removing stale fallback default_home presence entity: %s",
                stale_default_home_ent,
            )
            ent_reg.async_remove(stale_default_home_ent)
        dev_reg = dr.async_get(hass)
        stale_dev = dev_reg.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_structure_default_home"), entry.entry_id
        )
        if stale_dev:
            _LOGGER.info(
                "Removing stale fallback default_home device: %s (%s)",
                stale_dev.name,
                stale_dev.id,
            )
            dev_reg.async_remove_device(stale_dev.id)

    # Repair contaminated identities before DeviceInfo registration can reuse them.
    repair_devices = [
        device
        for key in (DATA_COORDINATOR, DATA_CLOUD_COORDINATOR)
        if (repair_coordinator := entry_data.get(key)) is not None
        for device in repair_coordinator.data or []
    ]
    try:
        await async_repair_placeholder_macs(hass, entry, repair_devices)
    except Exception:
        _LOGGER.exception(
            "Placeholder-MAC registry repair failed; continuing integration setup"
        )

    # Initialize Bluetooth tracking if enabled and configured
    tracking = bool(entry.options.get(CONF_BLUETOOTH_TRACKING, False))
    subentries = (
        entry.get_subentries_of_type(SUBENTRY_BLUETOOTH_DEVICE)
        if hasattr(entry, "get_subentries_of_type")
        else []
    )
    local_coord_candidate: GoogleHomeDataUpdateCoordinator | None = entry_data.get(
        DATA_COORDINATOR
    )
    if tracking and subentries and local_coord_candidate:
        try:
            from .bluetooth import BluetoothAccountAdapter, BluetoothScanner
            from .bluetooth_coordinator import BluetoothCoordinator
            from .bluetooth_storage import async_history

            excluded = set(entry.options.get(CONF_BLUETOOTH_EXCLUDED, []))
            history = async_history(hass, entry)
            adapter = BluetoothAccountAdapter(local_coord_candidate, entry)
            scanner = BluetoothScanner(
                session,
                adapter,
                subentries,
                excluded,
                history,
            )
            bluetooth_coord = BluetoothCoordinator(hass, entry, scanner, history)
            entry_data["bluetooth_coordinator"] = bluetooth_coord
            _LOGGER.debug(
                "Bluetooth presence tracking initialized with %d devices",
                len(subentries),
            )
        except Exception as exc:
            _LOGGER.warning("Could not initialize Bluetooth tracking: %s", exc)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _on_coordinator_update() -> None:
        hass.async_create_task(_async_cleanup_stale_devices_and_entities(hass, entry))

    local_coord: GoogleHomeDataUpdateCoordinator | None = entry_data.get(
        DATA_COORDINATOR
    )
    if local_coord:
        entry.async_on_unload(local_coord.async_add_listener(_on_coordinator_update))

    cloud_coord: Any | None = entry_data.get(DATA_CLOUD_COORDINATOR)
    if cloud_coord:
        entry.async_on_unload(cloud_coord.async_add_listener(_on_coordinator_update))

    # The cleanup helper also handles a successful refresh with every service excluded.
    if local_coord is not None or cloud_coord is not None:
        await _async_cleanup_stale_devices_and_entities(hass, entry)

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow user to manually delete a device in Home Assistant UI if no longer present."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    local_coordinator = data.get(DATA_COORDINATOR)
    cloud_coordinator = data.get(DATA_CLOUD_COORDINATOR)

    active_device_ids: set[str] = set()
    if local_coordinator and local_coordinator.data:
        for dev in local_coordinator.data:
            active_device_ids.add(dev.device_id)

    if cloud_coordinator and cloud_coordinator.data:
        for cdev in cloud_coordinator.data:
            active_device_ids.add(cdev.device_id)
        active_device_ids.add(f"{entry.entry_id}_routines")

    # If any identifier belongs to active devices, prevent deletion
    for ident in device_entry.identifiers:
        if ident[0] == DOMAIN and ident[1] in active_device_ids:
            return False

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if "bluetooth_coordinator" in entry_data:
        try:
            entry_data["bluetooth_coordinator"].stop()
        except Exception:
            pass
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


def saved_interval(entry: ConfigEntry) -> int:
    """Return the update interval in the options, in seconds."""
    return cast(
        int,
        entry.options.get(
            CONF_LOCAL_UPDATE_INTERVAL,
            entry.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL),
        ),
    )


@callback
def async_show_polling_disabled(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Show a repair while polling is turned off, which can turn it back on."""
    if not entry.pref_disable_polling:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_POLLING_DISABLED)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_POLLING_DISABLED,
        data={"entry_id": entry.entry_id},
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_POLLING_DISABLED,
    )


@callback
def async_show_invalid_interval(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Show a repair while the saved update interval is below 1 second and polling is on."""
    if saved_interval(entry) >= MIN_UPDATE_INTERVAL or entry.pref_disable_polling:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_INVALID_INTERVAL)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_INVALID_INTERVAL,
        data={"entry_id": entry.entry_id},
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_INVALID_INTERVAL,
        translation_placeholders={"min_interval": str(MIN_UPDATE_INTERVAL)},
    )


__all__ = [
    "async_migrate_entry",
    "async_reload_entry",
    "async_remove_config_entry_device",
    "async_setup_entry",
    "async_show_invalid_interval",
    "async_show_polling_disabled",
    "async_unload_entry",
    "saved_interval",
]
