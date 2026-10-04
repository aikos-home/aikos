"""Quiet hours active right now (switches exactly at start and end, without polling); the front door (front_door.py); mic
problems (mic_problem.py, W3)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from . import AikosConfigEntry
from .entity import AikosEntity
from .front_door import FrontDoor
from .mic_problem import MicProblem
from .quiet_hours import is_quiet, next_change


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([QuietHoursActive(entry, "quiet_hours_active", "binary_sensor.aikos_quiet_hours"),
                        FrontDoor(entry, "front_door", "binary_sensor.aikos_front_door"),
                        MicProblem(entry, "mic_problem", "binary_sensor.aikos_mic_problem", "aikos_mic_check", announce=True),
                        MicProblem(entry, "mic_problem_test", "binary_sensor.aikos_mic_problem_test", "aikos_mic_check_test",
                                   announce=False)])


class QuietHoursActive(AikosEntity, BinarySensorEntity):
    _unsub_timer: CALLBACK_TYPE | None = None

    @property
    def is_on(self) -> bool:
        s = self.settings
        return s.enabled and is_quiet(dt_util.now().time(), s.start, s.end)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.settings
        return {"start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M")}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.settings.add_listener(self._refresh))
        self.async_on_remove(self._cancel_timer)
        self._schedule()

    @callback
    def _on_timer(self, _now: datetime) -> None:
        self._unsub_timer = None                     # this timer has fired; nothing left to cancel
        self._refresh()

    @callback
    def _refresh(self) -> None:
        self._schedule()
        self.async_write_ha_state()

    @callback
    def _schedule(self) -> None:
        self._cancel_timer()
        s = self.settings
        when = next_change(dt_util.now(), s.start, s.end)
        if when is not None:
            self._unsub_timer = async_track_point_in_time(self.hass, self._on_timer, when)

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None
