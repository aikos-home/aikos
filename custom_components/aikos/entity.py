"""Common base of all aikos entities: they belong to the one "aikos" device."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER


class AikosEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str, entity_id: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        # Fixed English ids, the same in every house and every HA language (contract: created once, never changed).
        self.entity_id = entity_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="aikos",
            manufacturer=MANUFACTURER,
            model="aikos",
            sw_version=entry.runtime_data.version,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def settings(self):
        return self._entry.runtime_data.quiet_hours
