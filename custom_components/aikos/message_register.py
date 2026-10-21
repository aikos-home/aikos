"""The door message register in Home Assistant (aikos-app A10, A15, A27, A38): listens to the door, keeps the list in
HA's storage (.storage/aikos.door_messages), deletes a message's MP3 with it.

Sources (the door's contracts): `esphome.aikos_door_message {recipient, source}` from the screen when a recording starts,
`binary_sensor.aikos_intercom_talk_message_recording`, the door transcripts `sensor.talk_transcript_door`, and the
recorder's `aikos_door_message_saved {file, seconds, recipient}` / `aikos_door_message_failed`. Who may see, hear or delete
a message is decided by the aikos app (the residents' only way in); Home Assistant keeps the data (A16).
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOOR_FAILED_EVENT,
    DOOR_MEDIA_FOLDER,
    DOOR_MESSAGE_RECORDING,
    DOOR_RECIPIENT_EVENT,
    DOOR_SAVED_EVENT,
    LIVE_TRANSCRIPT_DOOR,
)
from .door_messages import DoorMessage, Register, safe_file

_LOGGER = logging.getLogger(__name__)
STORE_KEY = "aikos.door_messages"
STORE_VERSION = 1
INVALID = ("unknown", "unavailable", "")


def _scan(folder: Path) -> dict[str, float]:
    try:
        with os.scandir(folder) as it:
            return {e.name: e.stat().st_mtime for e in it if e.is_file() and e.name.endswith(".mp3")}
    except FileNotFoundError:
        return {}


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)


class DoorMessageRegister:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, STORE_KEY)
        self.rules = Register()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._present: set[str] = set()

    @property
    def folder(self) -> Path | None:
        local = self._hass.config.media_dirs.get("local")
        return Path(local) / DOOR_MEDIA_FOLDER if local else None

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self.rules = Register.from_dict(data)
        await self._sync_folder()

    @callback
    def start(self) -> None:
        if self._unsubs:
            return
        bus = self._hass.bus
        self._unsubs += [
            bus.async_listen(DOOR_RECIPIENT_EVENT, self._on_recipient),
            bus.async_listen(DOOR_SAVED_EVENT, self._on_saved),
            bus.async_listen(DOOR_FAILED_EVENT, self._on_failed),
            async_track_state_change_event(self._hass, [DOOR_MESSAGE_RECORDING], self._on_recording),
            async_track_state_change_event(self._hass, [LIVE_TRANSCRIPT_DOOR], self._on_transcript),
        ]

    @callback
    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_flush(self) -> None:
        """Write a pending change now (unload or reload; a Home Assistant stop flushes by itself)."""
        await self._store.async_save(self.rules.to_dict())

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(self.rules.to_dict, 1)
        for update in list(self._listeners):
            update()

    # the door
    @callback
    def _on_recipient(self, event: Event) -> None:
        self.rules.recipient_chosen(str(event.data.get("recipient") or ""), dt_util.utcnow())

    @callback
    def _on_recording(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None:
            return
        was_on, now_on = old is not None and old.state == "on", new.state == "on"
        if now_on != was_on:
            self.rules.recording(now_on, new.last_changed)

    @callback
    def _on_transcript(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None or new.state in INVALID or (old is not None and old.state == new.state):
            return                     # a new transcript has a new state (its time); attribute updates are not new words
        a = new.attributes
        if self.rules.words(str(a.get("message") or a.get("text") or ""), str(a.get("speaker") or ""), new.last_changed):
            self._changed()

    @callback
    def _on_failed(self, event: Event) -> None:
        self.rules.failed()

    @callback
    def _on_saved(self, event: Event) -> None:
        d = event.data
        before = self.rules.revision
        m = self.rules.saved(str(d.get("file") or ""), d.get("seconds"), str(d.get("recipient") or ""), dt_util.utcnow())
        if m is None:
            _LOGGER.warning("aikos: door message with an unusable file name ignored: %r", d.get("file"))
            return
        self._present.add(m.file)
        if self.rules.revision != before:
            self._changed()

    # the residents (through the aikos app)
    async def _sync_folder(self) -> None:
        folder = self.folder
        if folder is None:
            return
        files = await self._hass.async_add_executor_job(_scan, folder)
        self._present = set(files)
        if self.rules.adopt({n: dt_util.utc_from_timestamp(t) for n, t in files.items()}):
            self._changed()

    async def async_list(self) -> list[dict[str, Any]]:
        await self._sync_folder()
        return [dict(m.as_dict(), file_missing=m.file not in self._present) for m in self.rules.listing()]

    async def async_delete(self, msg_id: str, by: str) -> DoorMessage | None:
        """Deletes the MP3 first, then the entry: a file that can't be deleted keeps its entry (the error goes up)."""
        m = self.rules.get(msg_id)
        if m is None:
            return None
        folder = self.folder
        if folder is not None and safe_file(m.file):
            await self._hass.async_add_executor_job(_remove, folder / m.file)
        self._present.discard(m.file)
        self.rules.remove(msg_id)
        self._changed()
        if self._hass.services.has_service("logbook", "log"):
            local = dt_util.as_local(dt_util.parse_datetime(m.time) or dt_util.utcnow()).strftime("%d.%m. %H:%M")
            await self._hass.services.async_call("logbook", "log", {
                "name": "aikos Türnachricht", "entity_id": "sensor.aikos_door_messages",
                "message": f"vom {local} gelöscht" + (f" ({by})" if by else "")})
        return m

    async def async_heard(self, msg_id: str, by: str) -> bool | None:
        if self.rules.get(msg_id) is None:
            return None
        if self.rules.heard(msg_id, by):
            self._changed()
        return True
