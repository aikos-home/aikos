"""Quiet hours start and end."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AikosConfigEntry
from .entity import AikosEntity


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([
        QuietHoursTime(entry, "quiet_hours_start", "time.aikos_quiet_hours_start", "start"),
        QuietHoursTime(entry, "quiet_hours_end", "time.aikos_quiet_hours_end", "end"),
    ])


class QuietHoursTime(AikosEntity, TimeEntity):
    def __init__(self, entry: AikosConfigEntry, key: str, entity_id: str, field: str) -> None:
        super().__init__(entry, key, entity_id)
        self._field = field

    @property
    def native_value(self) -> time:
        return getattr(self.settings, self._field)

    async def async_set_value(self, value: time) -> None:
        self.settings.update(**{self._field: value})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.settings.add_listener(self.async_write_ha_state))
