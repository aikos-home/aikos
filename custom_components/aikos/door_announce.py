"""The door announcements (sprachausgabe S10–S14): after a ring, one sentence in a resident's own voice when a situation
applies (a parcel expected, everybody away, bell muted or quiet hours), as far as the disclosure level allows. A parcel
expected also speaks when someone only comes close (S14). The rules are announce_rules.py; this block watches Home
Assistant and keeps each sentence made in advance, so it plays at once.

Kept in HA's storage (.storage/aikos.door_announcements). Inputs: the doorbell and the residents (options, as for the ring
push), the parcel sensor (option; on = a delivery is expected today), the bell mute, the quiet hours. Nothing is said
during a call or while a message is recorded, and nothing without a voice and a voice service.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .announce_rules import (
    PARCEL,
    PLACE_MAX,
    SITUATIONS,
    Announcements,
    Resident,
    clean,
    may_repeat,
    pick,
    sentence,
)
from .const import DOOR_MESSAGE_RECORDING, LIVE_CALL, OPT_DOORBELL, OPT_PARCEL, OPT_RESIDENTS
from .door_speech import DoorSpeech
from .quiet_hours import is_quiet
from .ring_notifier import is_ring
from .settings import QuietHoursSettings

_LOGGER = logging.getLogger(__name__)
STORE_KEY = "aikos.door_announcements"
RING_DELAY = 1.5        # s: the visitor hears the door's own ring first
SETTLE = 5              # s: residents moving between zones settle before their sentence is made again
EVENT = "aikos_door_announced"


class DoorAnnouncer:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, speech: DoorSpeech, quiet: QuietHoursSettings,
                 muted: Callable[[], bool]) -> None:
        self._hass = hass
        self._entry = entry
        self._speech = speech
        self._quiet = quiet
        self._muted = muted
        self._store: Store[dict[str, Any]] = Store(hass, 1, STORE_KEY)
        self.state = Announcements()
        self.ready: dict[str, tuple[str, str]] = {}
        """situation → (sentence, file) made in advance."""
        self.last: dict[str, str] = {}
        """The last announcement: situation, text, at."""
        self._last_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._settle: Callable[[], None] | None = None

    # life cycle
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.state = Announcements.from_dict(data.get("config"))
        ready = data.get("ready") if isinstance(data.get("ready"), dict) else {}
        self.ready = {k: (str(v[0]), str(v[1])) for k, v in ready.items()
                      if k in SITUATIONS and isinstance(v, list) and len(v) == 2}
        self.last = {k: str(v) for k, v in (data.get("last") or {}).items()} if isinstance(data.get("last"), dict) else {}

    def _data(self) -> dict[str, Any]:
        return {"config": self.state.to_dict(), "ready": {k: list(v) for k, v in self.ready.items()}, "last": self.last}

    @callback
    def start(self) -> None:
        """(Re)subscribe from the current options."""
        self.stop()
        o = self._entry.options
        if o.get(OPT_DOORBELL):
            self._unsubs.append(async_track_state_change_event(self._hass, [o[OPT_DOORBELL]], self._on_bell))
        inputs = [*o.get(OPT_RESIDENTS, []), *([o[OPT_PARCEL]] if o.get(OPT_PARCEL) else []), "binary_sensor.aikos_quiet_hours",
                  "binary_sensor.aikos_bell_muted"]
        self._unsubs.append(async_track_state_change_event(self._hass, inputs, self._on_input))
        self._background(self._prepare())

    @callback
    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._settle is not None:
            self._settle()
            self._settle = None

    async def async_flush(self) -> None:
        await self._store.async_save(self._data())

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(self._data, 1)
        for update in list(self._listeners):
            update()

    @callback
    def _background(self, coro) -> None:
        self._entry.async_create_background_task(self._hass, coro, "aikos door announcement")

    # the house now
    def residents(self) -> list[Resident]:
        zones = {}
        for zone_id, phrase in self.state.places.items():
            z = self._hass.states.get(zone_id)
            if z is not None:
                zones[z.name] = phrase
        out = []
        for person in self._entry.options.get(OPT_RESIDENTS, []):
            st = self._hass.states.get(person)
            if st is None:
                out.append(Resident(person, "unknown"))
                continue
            place = zones.get(st.state, "") if person in self.state.named else ""
            out.append(Resident(st.name, st.state, place))
        return out

    def _parcel(self) -> bool:
        sensor = self._entry.options.get(OPT_PARCEL)
        st = self._hass.states.get(sensor) if sensor else None
        return st is not None and st.state == "on"

    def _quiet_or_muted(self) -> bool:
        q = self._quiet
        return self._muted() or (q.enabled and is_quiet(dt_util.now().time(), q.start, q.end))

    def _busy(self) -> bool:
        return any((s := self._hass.states.get(e)) is not None and s.state == "on" for e in (LIVE_CALL, DOOR_MESSAGE_RECORDING))

    def now(self) -> tuple[str, str] | None:
        """What a ring would get right now: (situation, sentence), or None."""
        return pick(self.state, parcel=self._parcel(), muted=self._quiet_or_muted(), residents=self.residents())

    # settings (from the app or the number entity)
    async def async_set(self, *, disclosure: int | None = None, texts: dict[str, str] | None = None,
                        away_places: str | None = None, places: dict[str, str] | None = None,
                        named: list[str] | None = None, voice: str | None = None) -> Announcements:
        a = Announcements.from_dict(self.state.to_dict())
        if disclosure is not None:
            a.disclosure = int(disclosure)
        if texts is not None:
            for k, v in texts.items():
                if k not in SITUATIONS:
                    raise ValueError(f"unknown situation {k}")
                a.texts[k] = clean(v)
            a.texts = {k: v for k, v in a.texts.items() if v}
        if away_places is not None:
            a.away_places = clean(away_places)
        if places is not None:
            a.places = {str(k): clean(v, PLACE_MAX) for k, v in places.items() if clean(v, PLACE_MAX)}
        if named is not None:
            a.named = [str(p) for p in dict.fromkeys(named)]
        if voice is not None:
            a.voice = voice
        a.check()
        self.state = a
        self._changed()
        self._background(self._prepare())
        return a

    # made in advance
    @callback
    def _on_input(self, _event: Event[EventStateChangedData]) -> None:
        for update in list(self._listeners):   # what a ring would get now may have changed
            update()
        if self._settle is not None:
            self._settle()
        self._settle = async_call_later(self._hass, SETTLE, self._settled)

    @callback
    def _settled(self, _now: datetime) -> None:
        self._settle = None
        self._background(self._prepare())

    async def _prepare(self) -> None:
        """Make each sentence that can be said at this level, as it would be said now, unless it is ready already."""
        async with self._lock:
            for s in SITUATIONS:
                text = sentence(self.state, s, self.residents()) if self.state.voice else ""
                have = self.ready.get(s)
                if have and have[0] == text:
                    continue
                if not text:
                    self.ready.pop(s, None)
                    await self._speech.drop(f"announce-{s}")
                    self._changed()
                    continue
                name = await self._speech.make(text, self.state.voice, f"announce-{s}")
                if name:
                    self.ready[s] = (text, name)
                    self._changed()

    # saying it
    @callback
    def _on_bell(self, event: Event[EventStateChangedData]) -> None:
        if is_ring(event.data["old_state"], event.data["new_state"]):
            self._background(self._after_ring())

    async def _after_ring(self) -> None:
        await asyncio.sleep(RING_DELAY)
        await self._announce(only=None)

    async def on_approach(self) -> bool:
        """Someone came close (the radar): only a parcel expected speaks then (S14). True = it spoke."""
        return await self._announce(only=PARCEL)

    async def _announce(self, only: str | None) -> bool:
        now = dt_util.now()
        if self._busy() or not may_repeat(self._last_at, now) or not self.state.voice:
            return False
        got = self.now()
        if got is None or (only is not None and got[0] != only):
            return False
        situation, text = got
        self._last_at = now
        ready = self.ready.get(situation)
        if ready and ready[0] == text:
            played = await self._speech.play(ready[1])
        else:  # not made yet (the residents just moved): made now, a little later
            played = await self._speech.say_now(text, self.state.voice, "announce-now")
        if not played:
            return False
        self.last = {"situation": situation, "text": text, "at": now.isoformat(timespec="seconds")}
        self._changed()
        self._hass.bus.async_fire(EVENT, {"situation": situation, "text": text})
        if self._hass.services.has_service("logbook", "log"):
            await self._hass.services.async_call("logbook", "log", {
                "name": "aikos Tür", "entity_id": "sensor.aikos_door_announcements", "message": f"angesagt: {text}"})
        return True
