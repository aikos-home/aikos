"""The call log sensors: `sensor.aikos_call_log` (live) and `sensor.aikos_call_log_test` (bench, test entities only).

Contract for the devices (unchanged from the former package): attributes `call_id`, `active`, `last_id`, `messages`,
`messages_json` (newest 10, JSON text; per message `id`, `side` door/room, `who`, `text`).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from . import AikosConfigEntry
from .call_log import CallLog
from .const import (
    LIVE_CALL,
    LIVE_TRANSCRIPT_DOOR,
    LIVE_TRANSCRIPT_ROOM,
    TEST_CALL,
    TEST_NEW_CALL,
    TEST_TRANSCRIPT_DOOR,
    TEST_TRANSCRIPT_ROOM,
)
from .entity import AikosEntity


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([
        CallLogSensor(entry, "call_log", "sensor.aikos_call_log", LIVE_TRANSCRIPT_ROOM, LIVE_TRANSCRIPT_DOOR, LIVE_CALL,
                      new_call_button=None, announce=True),
        CallLogSensor(entry, "call_log_test", "sensor.aikos_call_log_test", TEST_TRANSCRIPT_ROOM, TEST_TRANSCRIPT_DOOR, TEST_CALL,
                      new_call_button=TEST_NEW_CALL, announce=False),
    ])


def _iso(state: State) -> str:
    return state.last_changed.isoformat(timespec="seconds")


class CallLogSensor(AikosEntity, RestoreEntity, SensorEntity):
    def __init__(self, entry: AikosConfigEntry, key: str, entity_id: str, room: str, door: str, call: str,
                 new_call_button: str | None, announce: bool) -> None:
        super().__init__(entry, key, entity_id)
        self._room, self._door, self._call, self._button = room, door, call, new_call_button
        self._announce = announce                    # live log only: event + logbook for every new message
        self._log = CallLog()
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        return self._log.last_time or self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "call_id": self._log.call_id,
            "active": self._in_call(),
            "last_id": self._log.last_id,
            "messages": [dict(m) for m in self._log.messages],
            "messages_json": self._log.feed_json(),
        }

    def _in_call(self) -> bool:
        state = self.hass.states.get(self._call) if self.hass else None
        return state is not None and state.state == "on"

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None:
            self._state = last.state if last.state not in ("unknown", "unavailable") else None
            messages = last.attributes.get("messages")
            if isinstance(messages, list) and all(isinstance(m, dict) and "id" in m for m in messages):
                self._log.messages = [dict(m) for m in messages]
            self._log.call_id = str(last.attributes.get("call_id") or "")
        watched = [self._room, self._door, self._call] + ([self._button] if self._button else [])
        self.async_on_remove(async_track_state_change_event(self.hass, watched, self._on_change))

    @callback
    def _on_change(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        before = self._log.last_id
        if entity_id == self._call:
            if new is None:
                return
            was_on, now_on = old is not None and old.state == "on", new.state == "on"
            if now_on and not was_on:
                self._log.start(_iso(new))
            elif was_on and not now_on:
                self._log.end()
            else:
                return
        elif entity_id == self._button:
            if new is None or new.state in ("unknown", "unavailable"):
                return
            self._log.start(new.state)
        else:
            if new is None or not self._in_call():   # R22: nothing is added outside a call
                return
            side = "door" if entity_id == self._door else "room"
            if not self._log.add(side, new.state, new.attributes):
                return
        if self._log.last_time:
            self._state = self._log.last_time
        self.async_write_ha_state()
        if self._announce and self._log.last_id and self._log.last_id != before:
            self._tell(self._log.messages[-1])

    @callback
    def _tell(self, m: dict[str, Any]) -> None:
        self.hass.bus.async_fire("aikos_call_message", {
            "call_id": self._log.call_id, "id": m["id"], "side": m["side"], "who": m["who"], "role": m["role"],
            "text": m["text"], "urgent": m["urgent"], "lang": m["lang"]})
        if self.hass.services.has_service("logbook", "log"):
            lang = f" ({m['lang']})" if m["lang"] else ""
            self.hass.async_create_task(self.hass.services.async_call("logbook", "log", {
                "name": "aikos Gespräch", "message": f"{m['who']}{lang}: {m['text']}", "entity_id": self.entity_id}))
