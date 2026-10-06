"""DataUpdateCoordinator for Google Home integration."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from aiohttp import ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    EVENT_ALARM_TRIGGERED,
    EVENT_TIMER_FINISHED,
    FIRMWARE_CHECK_INTERVAL,
    FIRMWARE_VERSIONS_URL,
)
from .exceptions import AuthenticationFailed, InvalidMasterToken, TwoFactorRequired
from .models import GoogleHomeAlarmStatus, GoogleHomeDevice, GoogleHomeTimerStatus

if TYPE_CHECKING:
    from .api import GlocaltokensApiClient

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeDataUpdateCoordinator(DataUpdateCoordinator[list[GoogleHomeDevice]]):
    """Class to manage fetching data from Google Home devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: GlocaltokensApiClient,
        update_interval: int,
    ) -> None:
        """Initialize."""
        self.client = client
        self._device_cache: dict[str, GoogleHomeDevice] = {}
        self._previous_active_timers: dict[str, set[str]] = {}
        self._previous_active_alarms: dict[str, set[str]] = {}
        self._firmware_data: dict[str, Any] = {}
        self._last_firmware_fetch: datetime | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> list[GoogleHomeDevice]:
        """Update data via client and fire events for finished timers / triggered alarms."""
        try:
            devices = await self.client.update_google_devices_information()
            if devices:
                for dev in devices:
                    self._device_cache[dev.device_id] = dev
            await self._async_sync_firmware_versions(devices)
            self._check_and_fire_events(devices)
            return devices
        except ConfigEntryAuthFailed:
            raise
        except (AuthenticationFailed, InvalidMasterToken, TwoFactorRequired) as err:
            raise ConfigEntryAuthFailed(
                f"Google Home authentication expired or invalid: {err}"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Error updating Google Home devices: {err}") from err

    async def _async_sync_firmware_versions(
        self, devices: list[GoogleHomeDevice]
    ) -> None:
        """Fetch remote firmware versions and match them against known devices."""
        now = datetime.now(UTC)
        # Fetch remote firmware catalog once every 24 hours or on startup
        if (
            not self._firmware_data
            or self._last_firmware_fetch is None
            or (now - self._last_firmware_fetch) > FIRMWARE_CHECK_INTERVAL
        ):
            await self._async_load_firmware_catalog()

        prod_versions: dict[str, dict[str, str]] = self._firmware_data.get(
            "production", {}
        )
        if not prod_versions:
            return

        for dev in devices:
            self._apply_firmware_to_device(dev, prod_versions)

    async def _async_load_firmware_catalog(self) -> None:
        """Load firmware catalog from GitHub raw URL."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                FIRMWARE_VERSIONS_URL, timeout=ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    data = json.loads(text)
                    if isinstance(data, dict) and "production" in data:
                        self._firmware_data = data
                        self._last_firmware_fetch = datetime.now(UTC)
                        _LOGGER.debug(
                            "Loaded %s firmware definitions from GitHub",
                            len(data["production"]),
                        )
        except Exception as exc:
            _LOGGER.debug(
                "Could not fetch remote firmware versions from GitHub: %s", exc
            )

    def _apply_firmware_to_device(
        self,
        dev: GoogleHomeDevice,
        prod_versions: dict[str, dict[str, str]],
    ) -> None:
        """Find matching firmware entry for device based on hardware or name."""
        hw = (dev.hardware or "").lower()
        nm = (dev.name or "").lower()

        # Sort by length descending to match specific models before general ones
        sorted_keys = sorted(prod_versions.keys(), key=lambda k: -len(k))
        for key in sorted_keys:
            # e.g. "Google Nest Audio" -> target "nest audio"
            target = key.lower().replace("google ", "").strip()
            if target in hw or target in nm:
                info = prod_versions[key]
                latest_ver = info.get("firmware_version")
                notes = info.get("release_notes")
                if latest_ver:
                    dev.latest_firmware_version = latest_ver
                if notes:
                    dev.release_notes = notes
                break

    def _check_and_fire_events(self, devices: list[GoogleHomeDevice]) -> None:
        """Check for expired timers and triggered alarms and fire HA bus events."""
        for device in devices:
            device_id = device.device_id

            # Check Timers
            current_active_timers = {
                t.timer_id: t
                for t in device.get_sorted_timers()
                if t.status == GoogleHomeTimerStatus.SET
            }
            prev_timer_ids = self._previous_active_timers.get(device_id, set())

            # Detect timers that disappeared (finished/expired)
            for old_id in prev_timer_ids:
                if old_id not in current_active_timers:
                    self.hass.bus.async_fire(
                        EVENT_TIMER_FINISHED,
                        {
                            "device_id": device_id,
                            "device_name": device.name,
                            "timer_id": old_id,
                        },
                    )

            self._previous_active_timers[device_id] = set(current_active_timers.keys())

            # Check Alarms
            current_active_alarms = {
                a.alarm_id: a
                for a in device.get_sorted_alarms()
                if a.status == GoogleHomeAlarmStatus.SET
            }
            prev_alarm_ids = self._previous_active_alarms.get(device_id, set())

            for old_id in prev_alarm_ids:
                if old_id not in current_active_alarms:
                    self.hass.bus.async_fire(
                        EVENT_ALARM_TRIGGERED,
                        {
                            "device_id": device_id,
                            "device_name": device.name,
                            "alarm_id": old_id,
                        },
                    )

            self._previous_active_alarms[device_id] = set(current_active_alarms.keys())

    def get_device(self, device_id: str) -> GoogleHomeDevice | None:
        """Get device by ID from latest coordinator data."""
        if self.data:
            for device in self.data:
                if device.device_id == device_id:
                    return device
        return self._device_cache.get(device_id)
