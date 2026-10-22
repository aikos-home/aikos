"""The call log sensors: `sensor.aikos_call_log` (live) and `sensor.aikos_call_log_test` (bench, test entities only); the door
message register's `sensor.aikos_door_messages`; the door actions' note, greeting and picture (door_entities.py); the door
announcements (announce_entities.py).

Contract for the devices (unchanged from the former package): attributes `call_id`, `active`, `last_id`, `messages`,
`messages_json` (newest 10, JSON text; per message `id`, `side` door/room, `who`, `text`; new since 0.6.0: `tr`, `tr_lang`),
`visitor_language`, `visitor_language_name` (R28).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import AikosConfigEntry
from .app_talker import KEY as APP_TALKER_KEY
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
from .announce_entities import DoorAnnouncements
from .door_entities import DoorGreeting, DoorNote, DoorPicture
from .entity import AikosEntity


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([
        CallLogSensor(entry, "call_log", "sensor.aikos_call_log", LIVE_TRANSCRIPT_ROOM, LIVE_TRANSCRIPT_DOOR, LIVE_CALL,
                      new_call_button=None, announce=True),
        CallLogSensor(entry, "call_log_test", "sensor.aikos_call_log_test", TEST_TRANSCRIPT_ROOM, TEST_TRANSCRIPT_DOOR, TEST_CALL,
                      new_call_button=TEST_NEW_CALL, announce=False),
        DoorMessagesSensor(entry),
        DoorNote(entry, "door_note", "sensor.aikos_door_note"),
        DoorGreeting(entry, "door_greeting", "sensor.aikos_door_greeting"),
        DoorAnnouncements(entry, "door_announcements", "sensor.aikos_door_announcements"),
        DoorPicture(entry, "door_picture", "sensor.aikos_door_picture"),
        DoorRing(entry, "door_ring", "sensor.aikos_door_ring"),
        DoorThreadSensor(entry, "door_thread", "sensor.aikos_door_thread"),
        AppTalkerSensor(entry, "app_talker", f"sensor.{APP_TALKER_KEY}_ip_address"),
    ])


class AppTalkerSensor(AikosEntity, SensorEntity):
    """Who talks to the door from the app (app_talker.py): state = the app node's address, "" when nobody does; its
    friendly name is "<person> IP address", which is how the transcriber names a sender."""

    _attr_has_entity_name = False

    def __init__(self, entry: AikosConfigEntry, key: str, entity_id: str) -> None:
        super().__init__(entry, key, entity_id)
        self._attr_device_info = None   # under a device Home Assistant puts the device's name in front of the name

    @property
    def name(self) -> str:
        return f"{self._entry.runtime_data.app_talker.name or 'aikos App'} IP address"

    @property
    def native_value(self) -> str:
        return self._entry.runtime_data.app_talker.ip

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._entry.runtime_data.app_talker.add_listener(self.async_write_ha_state))


class DoorThreadSensor(AikosEntity, SensorEntity):
    """The door's conversation as one thread (door_thread.py): state = the newest entry's time; attributes `visit` (the
    newest visit's number) and `entries` (the newest 60, each `id`, `t`, `visit`, `kind`, `who`, `text`, …). The entries
    stay out of the recorder (they are in the thread's own storage)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unrecorded_attributes = frozenset({"entries"})

    @property
    def native_value(self) -> datetime | None:
        e = self._entry.runtime_data.door_thread.entries
        return dt_util.parse_datetime(e[-1]["t"]) if e else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = self._entry.runtime_data.door_thread
        return {"visit": t.visit, "entries": [dict(e) for e in t.entries]}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._entry.runtime_data.door_thread.add_listener(self.async_write_ha_state))


class DoorRing(AikosEntity, RestoreEntity, SensorEntity):
    """When the doorbell was last pressed (every press, whatever the push rules say): the aikos app pushes on it (A47)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: AikosConfigEntry, key: str, entity_id: str) -> None:
        super().__init__(entry, key, entity_id)
        self._restored: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        return self._entry.runtime_data.ring_notifier.last_ring or self._restored

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            self._restored = dt_util.parse_datetime(last.state)
        self.async_on_remove(self._entry.runtime_data.ring_notifier.add_listener(self.async_write_ha_state))


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
            "visitor_language": self._log.visitor_language,
            "visitor_language_name": self._log.visitor_language_name,
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
            self._log.visitor_language = str(last.attributes.get("visitor_language") or "")
            self._log.visitor_language_name = str(last.attributes.get("visitor_language_name") or "")
        watched = [self._room, self._door, self._call] + ([self._button] if self._button else [])
        self.async_on_remove(async_track_state_change_event(self.hass, watched, self._on_change))
        if self._announce:
            self.async_on_remove(self.hass.bus.async_listen("aikos_door_reply", self._on_app_reply))

    @callback
    def _on_app_reply(self, event: Event) -> None:
        """A typed answer from the app shown at the door (A49): a line of the call, as if said through a room key
        (R22: only during a call). A waiting answer or a voice message is not."""
        d = event.data
        if d.get("shown") is False or d.get("voice") or not self._in_call():
            return
        stamp = dt_util.now().isoformat(timespec="milliseconds")
        if self._log.add("room", stamp, {"speaker": d.get("sender") or "", "device": "app", "text": d.get("text") or ""}):
            self._state = self._log.last_time
            self.async_write_ha_state()
            if self._log.added:
                self._tell(self._log.added, via="text")

    @callback
    def _on_change(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        new_msg, via = None, ""
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
            new_msg = self._log.added
            via = "app" if side == "room" and new.attributes.get("key_id") == APP_TALKER_KEY else ""
        if self._log.last_time:
            self._state = self._log.last_time
        self.async_write_ha_state()
        if self._announce and new_msg:
            self._tell(new_msg, via=via)

    @callback
    def _tell(self, m: dict[str, Any], via: str = "") -> None:
        """`via`: "app" = said live from the aikos app, "text" = typed in the app, "" = a room key or the door."""
        self.hass.bus.async_fire("aikos_call_message", {
            "call_id": self._log.call_id, "id": m["id"], "side": m["side"], "who": m["who"], "role": m["role"],
            "text": m["text"], "urgent": m["urgent"], "lang": m["lang"], "via": via, "at": m.get("at") or m["t"]})
        if self.hass.services.has_service("logbook", "log"):
            lang = f" ({m['lang']})" if m["lang"] else ""
            self.hass.async_create_task(self.hass.services.async_call("logbook", "log", {
                "name": "aikos Gespräch", "message": f"{m['who']}{lang}: {m['text']}", "entity_id": self.entity_id}))


class DoorMessagesSensor(AikosEntity, SensorEntity):
    """State = number of door messages. `revision` changes with every change (new, words, heard, deleted), so a client
    without admin rights sees it through the state stream; the messages themselves come from `aikos.door_messages`."""

    def __init__(self, entry: AikosConfigEntry) -> None:
        super().__init__(entry, "door_messages", "sensor.aikos_door_messages")
        self._register = entry.runtime_data.door_messages

    @property
    def native_value(self) -> int:
        return len(self._register.rules)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        newest = next(iter(self._register.rules.listing()), None)
        return {"revision": self._register.rules.revision, "newest": newest.id if newest else "",
                "newest_time": newest.time if newest else ""}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._register.add_listener(self.async_write_ha_state))
