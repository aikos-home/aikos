"""The door's conversation as one thread, like a chat (aikos-app A49, the owner 22.10.: "wie so ein Chatlog"):
`sensor.aikos_door_thread`. Everything that happens at the door, in order:

| kind      | from                                                                                   |
|-----------|----------------------------------------------------------------------------------------|
| ring      | the doorbell (every press, as `sensor.aikos_door_ring`)                                |
| door      | what the visitor says (the call log's door side, `aikos_call_message`)                 |
| room      | what someone in the house says through a room key (the call log's room side)           |
| reply     | a resident's answer from the app, shown at the door (`aikos_door_reply`); `spoken` says whether it was read aloud |
| voice     | a resident's voice message from the app (recorded like on WhatsApp), played at the door; `spoken` = played  |
| waiting   | an answer or voice message that waits for the next visitor                             |
| announce  | the door's announcement after a ring (`aikos_door_announced`)                          |
| message   | the visitor left a message (`aikos_door_message_saved`)                                |

Unlike the call log (R22: emptied at the start and the end of a call, for the screens) the thread stays: the newest MAX
entries, kept in HA's storage (.storage/aikos.door_thread). A gap of VISIT_GAP or more starts a new visit (`visit`
counts up), so the app can show one visit at a time.
"""
from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOOR_SAVED_EVENT

STORE_KEY = "aikos.door_thread"
MAX = 60
TEXT_MAX = 600
VISIT_GAP = timedelta(minutes=5)
REPLY_EVENT = "aikos_door_reply"
SPOKEN_EVENT = "aikos_door_reply_spoken"
CALL_EVENT = "aikos_call_message"
ANNOUNCED_EVENT = "aikos_door_announced"


class DoorThread:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, 1, STORE_KEY)
        self.entries: list[dict[str, Any]] = []
        self.visit = 0
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        entries = data.get("entries") if isinstance(data, dict) else None
        self.entries = [e for e in entries if isinstance(e, dict)][-MAX:] if isinstance(entries, list) else []
        self.visit = int(data.get("visit") or 0) if isinstance(data, dict) else 0

    @callback
    def start(self, ring_listener: Callable[[Callable[[], None]], Callable[[], None]]) -> None:
        bus = self._hass.bus
        self._unsubs = [
            bus.async_listen(CALL_EVENT, self._on_call),
            bus.async_listen(REPLY_EVENT, self._on_reply),
            bus.async_listen(SPOKEN_EVENT, self._on_spoken),
            bus.async_listen(ANNOUNCED_EVENT, self._on_announced),
            bus.async_listen(DOOR_SAVED_EVENT, self._on_message),
            ring_listener(lambda: self.add("ring", "", "Es hat geklingelt")),
        ]

    @callback
    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_flush(self) -> None:
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"entries": self.entries, "visit": self.visit}

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def add(self, kind: str, who: str, text: str, **extra: Any) -> dict[str, Any]:
        now = dt_util.now()
        last = self.entries[-1] if self.entries else None
        if last is None or now - datetime.fromisoformat(last["t"]) >= VISIT_GAP:
            self.visit += 1
        entry = {"id": secrets.token_hex(4), "t": now.isoformat(timespec="seconds"), "visit": self.visit, "kind": kind,
                 "who": " ".join(str(who or "").split())[:60], "text": " ".join(str(text or "").split())[:TEXT_MAX], **extra}
        self.entries = (self.entries + [entry])[-MAX:]
        self._changed()
        return entry

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(self._data, 2)
        for update in list(self._listeners):
            update()

    @callback
    def _on_call(self, event: Event) -> None:
        d = event.data
        side = "door" if d.get("side") == "door" else "room"
        self.add(side, d.get("who") or ("Besucher" if side == "door" else "Haus"), d.get("text") or "",
                 lang=str(d.get("lang") or ""), urgent=bool(d.get("urgent")))

    @callback
    def _on_reply(self, event: Event) -> None:
        d = event.data
        shown = d.get("shown", True) is not False
        voice = str(d.get("voice") or "")
        kind = "waiting" if not shown else "voice" if voice else "reply"
        extra = {"voice": voice, "seconds": d.get("seconds")} if voice else {}
        self.add(kind, d.get("sender") or "", d.get("text") or "", spoken=None, **extra)

    @callback
    def _on_spoken(self, event: Event) -> None:
        """The answer was read aloud or the voice message played (or not): marked on the newest matching entry."""
        d = event.data
        ref, text = str(d.get("ref") or ""), " ".join(str(d.get("text") or "").split())[:TEXT_MAX]
        for e in reversed(self.entries):
            if e["kind"] not in ("reply", "voice", "waiting"):
                continue
            if (ref and e.get("voice") == ref) or (not ref and e["text"] == text and not e.get("voice")):
                e["spoken"] = bool(d.get("spoken"))
                self._changed()
                return

    @callback
    def _on_announced(self, event: Event) -> None:
        self.add("announce", "Tür", event.data.get("text") or "")

    @callback
    def _on_message(self, event: Event) -> None:
        seconds = event.data.get("seconds")
        length = f" ({round(float(seconds))} s)" if isinstance(seconds, (int, float)) else ""
        self.add("message", "Besucher", f"hat eine Nachricht hinterlassen{length}")
