"""Events for alarm and timer transitions seen in successful polls."""

from __future__ import annotations

import logging

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import GoogleHomeDataUpdateCoordinator
from .entity import GoogleHomeBaseEntity
from .models import GoogleHomeDevice
from .observations import ItemKind

_LOGGER: logging.Logger = logging.getLogger(__package__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Add both event entities when each supported device answers."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator: GoogleHomeDataUpdateCoordinator | None = entry_data.get(
        DATA_COORDINATOR
    )

    if coordinator is None:
        return True

    entities: list[GoogleHomeEvents] = []
    registered_device_ids: set[str] = set()

    def _create_entities_for_device(
        device: GoogleHomeDevice,
    ) -> list[GoogleHomeEvents]:
        registered_device_ids.add(device.device_id)
        return [
            AlarmEvents(
                coordinator=coordinator,
                device_id=device.device_id,
                device_name=device.name,
            ),
            TimerEvents(
                coordinator=coordinator,
                device_id=device.device_id,
                device_name=device.name,
            ),
        ]

    if coordinator.data:
        for device in coordinator.data:
            entities.extend(_create_entities_for_device(device))

    if entities:
        async_add_entities(entities)

    @callback
    def _async_add_new_devices() -> None:
        if not coordinator or not coordinator.data:
            return
        new_entities: list[GoogleHomeEvents] = []
        for dev in coordinator.data:
            if dev.device_id not in registered_device_ids:
                new_entities.extend(_create_entities_for_device(dev))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))
    return True


class GoogleHomeEvents(GoogleHomeBaseEntity, EventEntity):
    """Publish every item separately, consuming each coordinator batch only once."""

    _kind: ItemKind
    _consumed_sequence: int = -1

    @property
    def label(self) -> str:
        """Keep an independent registry identity for the kind of events."""
        return f"{self._kind}_events"

    async def async_added_to_hass(self) -> None:
        """Start listening without replaying changes from before entity addition."""
        self._consumed_sequence = self.coordinator.event_sequences.get(
            self.device_id, 0
        )
        await super().async_added_to_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write each event immediately so simultaneous items reach automations."""
        current_seq = self.coordinator.event_sequences.get(self.device_id, 0)
        if self._consumed_sequence != current_seq:
            self._consumed_sequence = current_seq
            events = self.coordinator.device_events.get(self.device_id, ())
            for event in events:
                if event.kind == self._kind:
                    self._trigger_event(event.event_type, event.attributes())
                    self.async_write_ha_state()
        super()._handle_coordinator_update()


class AlarmEvents(GoogleHomeEvents):
    """Observed alarm ringing, snoozing and ending under each reported ID."""

    _kind: ItemKind = "alarm"
    _attr_translation_key = "alarm_events"
    _attr_event_types = ["ringing", "snoozed", "stopped"]


class TimerEvents(GoogleHomeEvents):
    """Observed timer ringing and ending under each reported ID."""

    _kind: ItemKind = "timer"
    _attr_translation_key = "timer_events"
    _attr_event_types = ["ringing", "stopped"]
