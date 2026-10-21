"""The door actions for the aikos app in Home Assistant: bell mute, a note to the door, the door picture, the greeting.

Kept in HA's storage (.storage/aikos.door_actions). Uses the door's contracts (vertraege.md): `binary_sensor.aikos_bell_muted`
(provided here, the screen reads it), `text.aikos_intercom_screen_greeting`, `text.aikos_intercom_screen_photo_url`,
`esphome.aikos_intercom_screen_show_reply` (only while the radar sees someone), the radar
`binary_sensor.aikos_intercom_screen_someone_at_the_door`. Who may do what is decided by the aikos app.
"""
from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, time
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOOR_GREETING_TEXT,
    DOOR_MESSAGE_RECORDING,
    DOOR_PHOTO_URL,
    DOOR_SHOW_REPLY,
    DOOR_SOMEONE,
    LIVE_CALL,
)
from .door_picture import panel_png
from .door_rules import DoorState, Greeting, Mute, Note, check_window, clean_note, mute_until
from .door_speech import DoorSpeech, remove, write

_LOGGER = logging.getLogger(__name__)
STORE_KEY = "aikos.door_actions"
PICTURE_DIR = ("www", "aikos_door")             # served as /local/aikos_door without login: the picture is public anyway
AUDIO_MAX = 3 * 1024 * 1024
AUDIO_KINDS = {b"\x1aE\xdf\xa3": ".webm", b"OggS": ".ogg", b"RIFF": ".wav", b"ID3": ".mp3", b"\xff\xfb": ".mp3",
               b"\xff\xf3": ".mp3"}


def _audio_ext(data: bytes) -> str:
    for magic, ext in AUDIO_KINDS.items():
        if data.startswith(magic):
            return ext
    if data[4:8] == b"ftyp":
        return ".m4a"
    raise ValueError("not a sound file")


class DoorActions:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, speech: DoorSpeech) -> None:
        self._hass = hass
        self._entry = entry
        self._speech = speech
        self.approach: Callable[[], Awaitable[bool]] | None = None
        """Asked at an approach without a waiting note: True = it spoke to the visitor (the parcel announcement), so the
        greeting sound stays quiet this time."""
        self._store: Store[dict[str, Any]] = Store(hass, 1, STORE_KEY)
        self.state = DoorState()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._timers: list[Callable[[], None]] = []

    # life cycle
    async def async_load(self) -> None:
        self.state = DoorState.from_dict(await self._store.async_load())

    @callback
    def start(self) -> None:
        if self._unsubs:
            return
        self._unsubs.append(async_track_state_change_event(self._hass, [DOOR_SOMEONE], self._on_radar))
        self._unsubs.append(async_track_state_change_event(self._hass, [DOOR_GREETING_TEXT], self._on_screen_text))
        self._reschedule()
        self._hass.async_create_task(self._sync_greeting_text())

    @callback
    def stop(self) -> None:
        for unsub in self._unsubs + self._timers:
            unsub()
        self._unsubs.clear()
        self._timers.clear()

    async def async_flush(self) -> None:
        await self._store.async_save(self.state.to_dict())

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(self.state.to_dict, 1)
        self._reschedule()
        for update in list(self._listeners):
            update()

    @callback
    def _reschedule(self) -> None:
        for unsub in self._timers:
            unsub()
        self._timers.clear()
        now = dt_util.now()
        mute = self.state.mute
        if mute.on and mute.until:
            end = datetime.fromisoformat(mute.until)
            if end <= now:
                self.state.mute = Mute()
                self._store.async_delay_save(self.state.to_dict, 1)
            else:
                self._timers.append(async_track_point_in_time(self._hass, self._mute_over, end))
        nxt = self.state.greeting.next_change(now)
        if nxt is not None:
            self._timers.append(async_track_point_in_time(self._hass, self._greeting_window, nxt))

    @callback
    def _mute_over(self, _now: datetime) -> None:
        self.state.mute = Mute()
        self._changed()

    @callback
    def _greeting_window(self, _now: datetime) -> None:
        self._hass.async_create_task(self._sync_greeting_text())
        self._changed()

    # bell mute (A14/A40)
    @property
    def muted(self) -> bool:
        return self.state.mute.active(dt_util.now())

    @callback
    def mute(self, *, minutes: int | None = None, until_time: time | None = None, forever: bool = False) -> None:
        until = "" if forever else mute_until(dt_util.now(), minutes=minutes, until_time=until_time).isoformat(timespec="seconds")
        self.state.mute = Mute(on=True, until=until)
        self._changed()

    @callback
    def unmute(self) -> None:
        self.state.mute = Mute()
        self._changed()

    # a note to the door (A11/A39)
    def _someone_there(self) -> bool:
        st = self._hass.states.get(DOOR_SOMEONE)
        return st is not None and st.state == "on"

    async def async_say(self, message: str, sender: str, voice: str = "") -> str:
        """'now' (shown at the door, read aloud in `voice` if given) or 'waiting' (for the next visitor; its speech is
        made now, so it plays at once when someone comes)."""
        text, who = clean_note(message, sender)
        await self._drop_note_audio()
        if self._someone_there() and await self._show(text, who):
            self.state.note = None
            self._changed()
            if voice:
                self._background(self._speech.say_now(text, voice))
            return "now"
        note = Note(message=text, sender=who, since=dt_util.now().isoformat(timespec="seconds"), voice=voice)
        self.state.note = note
        self._changed()
        if voice:
            self._background(self._prepare_note(note))
        return "waiting"

    async def async_cancel_note(self) -> bool:
        had = self.state.note is not None
        await self._drop_note_audio()
        self.state.note = None
        self._changed()
        return had

    # speech in a resident's own voice (A42-A45)
    @callback
    def _background(self, coro) -> None:
        self._entry.async_create_background_task(self._hass, coro, "aikos door speech")

    async def _prepare_note(self, note: Note) -> None:
        name = await self._speech.make(note.message, note.voice, "note")
        if not name:
            return
        if self.state.note is note:   # still the same waiting note
            note.audio = name
            self._changed()
        elif self.state.note is None or not self.state.note.audio:
            # delivered or withdrawn before its speech was ready: nobody will play this file (a newer note's own file stays)
            await self._speech.drop("note")

    async def _drop_note_audio(self) -> None:
        if self.state.note is not None and self.state.note.audio:
            await self._speech.drop("note")

    async def _show(self, text: str, who: str) -> bool:
        if not self._hass.services.has_service("esphome", DOOR_SHOW_REPLY):
            return False
        await self._hass.services.async_call("esphome", DOOR_SHOW_REPLY, {"sender": who, "message": text}, blocking=True)
        self._hass.bus.async_fire("aikos_door_reply", {"sender": who, "text": text})
        if self._hass.services.has_service("logbook", "log"):
            await self._hass.services.async_call("logbook", "log", {
                "name": "aikos Tür", "entity_id": "sensor.aikos_door_note",
                "message": f"an die Tür{f' von {who}' if who else ''}: {text}"})
        return True

    @callback
    def _on_radar(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None or new.state != "on" or (old is not None and old.state == "on"):
            return
        self._hass.async_create_task(self._someone_came())

    async def _someone_came(self) -> None:
        note = self.state.note
        if note is not None:
            if await self._show(note.message, note.sender):
                self.state.note = None
                self._changed()
                if note.audio:
                    await self._speech.play(note.audio)
                    await self._speech.drop("note")
                elif note.voice:
                    await self._speech.say_now(note.message, note.voice)
            return  # the note is this visit's message; no greeting sound on top of it
        if self.approach is not None and await self.approach():
            return  # the parcel announcement was this visit's sound
        g = self.state.greeting
        busy = any((s := self._hass.states.get(e)) is not None and s.state == "on" for e in (LIVE_CALL, DOOR_MESSAGE_RECORDING))
        now = dt_util.now()
        if not g.may_play(now, busy):
            return
        if not await self._speech.play(g.sound):
            return
        g.last_played = now.isoformat(timespec="seconds")
        self._changed()

    # the door picture (A12/A41)
    def _picture_folder(self) -> Path:
        return Path(self._hass.config.path(*PICTURE_DIR))

    def picture_path(self) -> str:
        return f"/local/{PICTURE_DIR[1]}/{self.state.picture}" if self.state.picture else ""

    def _base_url(self) -> str:
        try:
            return get_url(self._hass, allow_external=False, allow_cloud=False, prefer_external=False)
        except NoURLAvailableError:
            return "http://homeassistant.local:8123"

    async def async_set_picture(self, data: bytes) -> str:
        png = await self._hass.async_add_executor_job(panel_png, data)
        name = f"foto-{secrets.token_hex(8)}.png"
        await self._hass.async_add_executor_job(write, self._picture_folder() / name, png, "foto-")
        self.state.picture = name
        await self._set_text(DOOR_PHOTO_URL, self._base_url() + self.picture_path())
        self._changed()
        return self.picture_path()

    async def async_clear_picture(self) -> None:
        await self._hass.async_add_executor_job(remove, self._picture_folder(), "foto-")
        self.state.picture = ""
        await self._set_text(DOOR_PHOTO_URL, "")
        self._changed()

    # the greeting (A13/A26)
    async def async_set_greeting(self, *, enabled: bool | None = None, text: str | None = None,
                                 start: datetime | None = None, end: datetime | None = None, clear_window: bool = False,
                                 audio: bytes | None = None, clear_audio: bool = False, voice: str | None = None) -> Greeting:
        g = self.state.greeting
        new = Greeting(**vars(g))
        new.managed = True
        if voice is not None:
            new.voice = voice
        if enabled is not None:
            new.enabled = enabled
        if text is not None:
            new.text = " ".join(text.split())[:120]
        if clear_window:
            new.start = new.end = ""
        if start is not None:
            new.start = dt_util.as_local(start).isoformat(timespec="seconds")
        if end is not None:
            new.end = dt_util.as_local(end).isoformat(timespec="seconds")
        check_window(datetime.fromisoformat(new.start) if new.start else None,
                     datetime.fromisoformat(new.end) if new.end else None)
        folder = self._speech.folder()
        if audio is not None:
            if folder is None:
                raise ValueError("no local media folder")
            if len(audio) > AUDIO_MAX:
                raise ValueError("sound file too large")
            name = f"greeting-{secrets.token_hex(6)}{_audio_ext(audio)}"
            await self._hass.async_add_executor_job(write, folder / name, audio, "greeting-")
            new.audio, new.last_played = name, ""
        elif clear_audio:
            if folder is not None:
                await self._hass.async_add_executor_job(remove, folder, "greeting-")
            new.audio = ""
        if (new.text, new.voice) != (g.text, g.voice) or not new.voice:
            new.tts_audio = ""   # the read-aloud text no longer fits: made again below
            await self._speech.drop("greeting")
        self.state.greeting = new
        self._changed()
        await self._sync_greeting_text()
        if new.text and new.voice and not new.tts_audio:
            self._background(self._prepare_greeting(new))
        return new

    async def _prepare_greeting(self, g: Greeting) -> None:
        name = await self._speech.make(g.text, g.voice, "greeting")
        if self.state.greeting is g and name:   # nobody changed the greeting meanwhile
            g.tts_audio = name
            self._changed()

    @callback
    def _on_screen_text(self, event: Event[EventStateChangedData]) -> None:
        old = event.data["old_state"]
        if old is None or old.state == "unavailable":   # the screen came back: give it the current greeting
            self._hass.async_create_task(self._sync_greeting_text())

    async def _sync_greeting_text(self) -> None:
        g = self.state.greeting
        if not g.managed:  # nobody set a greeting through aikos yet: the screen keeps whatever text it has
            return
        await self._set_text(DOOR_GREETING_TEXT, g.text if g.in_window(dt_util.now()) and g.text else "")

    async def _set_text(self, entity_id: str, value: str) -> None:
        st = self._hass.states.get(entity_id)
        if st is None or st.state == "unavailable" or st.state == value:
            return
        try:
            await self._hass.services.async_call("text", "set_value", {"entity_id": entity_id, "value": value}, blocking=True)
        except Exception as e:  # the screen being away must never break the app's action
            _LOGGER.warning("aikos: %s not set: %s", entity_id, e)
