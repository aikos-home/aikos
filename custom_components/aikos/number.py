"""The door's disclosure level (announce_entities.py)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AikosConfigEntry
from .announce_entities import Disclosure


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([Disclosure(entry, "door_disclosure", "number.aikos_door_disclosure")])
