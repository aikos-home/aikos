"""`binary_sensor.aikos_front_door`: the front door for the devices, debounced (2 s each way).

Devices only react to an off → on edge (opening the front door ends a call). A door open for more than 10 min is `stuck`
(attribute) and ends nothing more. Source = the entity chosen in the aikos options ("Front door sensor").
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import OPT_FRONT_DOOR
from .entity import AikosEntity

DEBOUNCE = timedelta(seconds=2)
STUCK_AFTER = timedelta(minutes=10)


def is_stuck(on_since: datetime | None, now: datetime) -> bool:
    return on_since is not None and now - on_since > STUCK_AFTER


class FrontDoor(AikosEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, entry, key: str, entity_id: str) -> None:
        super().__init__(entry, key, entity_id)
        self._source: str | None = None
        self._is_on = False
        self._on_since: datetime | None = None
        self._unsub_source: CALLBACK_TYPE | None = None
        self._unsub_debounce: CALLBACK_TYPE | None = None
        self._unsub_stuck: CALLBACK_TYPE | None = None

    @property
    def available(self) -> bool:
        state = self.hass.states.get(self._source) if self._source else None
        return state is not None and state.state in (STATE_ON, STATE_OFF)

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"source": self._source or "", "stuck": self._is_on and is_stuck(self._on_since, dt_util.utcnow())}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._entry.add_update_listener(self._options_changed))
        self.async_on_remove(self._stop)
        self._follow()

    async def _options_changed(self, hass, entry) -> None:
        if entry.options.get(OPT_FRONT_DOOR) != self._source:
            self._follow()

    @callback
    def _follow(self) -> None:
        self._stop()
        self._source = self._entry.options.get(OPT_FRONT_DOOR)
        source = self.hass.states.get(self._source) if self._source else None
        self._is_on = source is not None and source.state == STATE_ON          # a new source counts as it is, no edge
        self._on_since = source.last_changed if self._is_on else None
        if self._source:
            self._unsub_source = async_track_state_change_event(self.hass, [self._source], self._on_source)
        self._schedule_stuck()
        self.async_write_ha_state()

    @callback
    def _stop(self) -> None:
        for name in ("_unsub_source", "_unsub_debounce", "_unsub_stuck"):
            unsub = getattr(self, name)
            if unsub is not None:
                unsub()
                setattr(self, name, None)

    @callback
    def _on_source(self, event: Event[EventStateChangedData]) -> None:
        if self._unsub_debounce is not None:                            # a change within 2 s restarts the wait
            self._unsub_debounce()
            self._unsub_debounce = None
        new = event.data["new_state"]
        if new is None or new.state not in (STATE_ON, STATE_OFF):
            self.async_write_ha_state()                                 # unavailable now
            return
        wanted = new.state == STATE_ON
        if wanted != self._is_on:
            self._unsub_debounce = async_call_later(self.hass, DEBOUNCE, self._settle)
        else:
            self.async_write_ha_state()

    @callback
    def _settle(self, _now: datetime) -> None:
        self._unsub_debounce = None
        source = self.hass.states.get(self._source) if self._source else None
        if source is None or source.state not in (STATE_ON, STATE_OFF):
            self.async_write_ha_state()
            return
        self._is_on = source.state == STATE_ON
        self._on_since = dt_util.utcnow() if self._is_on else None
        self._schedule_stuck()
        self.async_write_ha_state()

    @callback
    def _schedule_stuck(self) -> None:
        if self._unsub_stuck is not None:
            self._unsub_stuck()
            self._unsub_stuck = None
        if self._is_on and self._on_since is not None:
            delay = max(0.0, (self._on_since + STUCK_AFTER - dt_util.utcnow()).total_seconds()) + 1
            self._unsub_stuck = async_call_later(self.hass, delay, self._stuck_now)

    @callback
    def _stuck_now(self, _now: datetime) -> None:
        self._unsub_stuck = None
        self.async_write_ha_state()
