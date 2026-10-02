"""Quiet hours on/off."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AikosConfigEntry
from .entity import AikosEntity


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([QuietHoursSwitch(entry, "quiet_hours", "switch.aikos_quiet_hours")])


class QuietHoursSwitch(AikosEntity, SwitchEntity):
    @property
    def is_on(self) -> bool:
        return self.settings.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.settings.update(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.settings.update(enabled=False)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.settings.add_listener(self.async_write_ha_state))
