"""The rules of the door actions for the aikos app (A11/A39, A12/A41, A13/A26, A14/A40), no Home Assistant code.

- Bell mute: for some minutes, until a time of day (the next one), or until switched off. Muted = the bell rings nowhere in
  the house; the door behaves as in quiet hours and the ring push still goes to the phones.
- A note to the door: shown right away if someone is at the door, else it waits for the next visitor and is gone after that.
  Read aloud in the sender's own voice if they have one (A45); a waiting note's speech is made in advance.
- The greeting: text and/or a recorded sound, for everyone who comes, within its time window, once per visit.
- The picture: a grey PNG for the door's welcome page, until it is removed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

NOTE_MAX = 400            # the screen's reply page (contract show_reply)
GREETING_MAX = 120        # text.aikos_intercom_screen_greeting
SENDER_MAX = 40
MUTE_MAX_MINUTES = 7 * 24 * 60
GREETING_PAUSE = timedelta(minutes=10)   # "once per visit": not again within this time


def mute_until(now: datetime, *, minutes: int | None = None, until_time: time | None = None) -> datetime:
    """When a mute ends. `now` is local time with zone; `until_time` is the next such time of day (tomorrow if passed)."""
    if minutes is not None:
        return now + timedelta(minutes=max(1, min(int(minutes), MUTE_MAX_MINUTES)))
    if until_time is not None:
        end = now.replace(hour=until_time.hour, minute=until_time.minute, second=0, microsecond=0)
        return end if end > now else end + timedelta(days=1)
    raise ValueError("minutes or until_time")


@dataclass
class Mute:
    on: bool = False
    until: str = ""
    """ISO time with zone; "" while on = until switched off."""

    def active(self, now: datetime) -> bool:
        if not self.on:
            return False
        return not self.until or now < datetime.fromisoformat(self.until)


@dataclass
class Note:
    message: str
    sender: str
    since: str
    voice: str = ""
    """The sender's voice at the TTS service; "" = shown only (A45)."""
    audio: str = ""
    """The speech made in advance (file in the greeting folder); "" = none (yet)."""


def clean_note(message: str, sender: str) -> tuple[str, str]:
    text = " ".join((message or "").split())[:NOTE_MAX]
    if not text:
        raise ValueError("empty message")
    return text, " ".join((sender or "").split())[:SENDER_MAX]


@dataclass
class Greeting:
    enabled: bool = False
    text: str = ""
    start: str = ""
    """ISO time with zone; "" = from now on."""
    end: str = ""
    """ISO time with zone; "" = until switched off."""
    audio: str = ""
    """File name of the recorded sound in the greeting folder; "" = none."""
    last_played: str = ""
    voice: str = ""
    """Whose voice reads the text when there is no recorded sound (the person who saved it, A45)."""
    tts_audio: str = ""
    """The text read aloud in that voice, made in advance (file in the greeting folder)."""
    managed: bool = False
    """Set once through aikos: from then on aikos owns the screen's greeting text (before that it leaves it alone)."""

    def in_window(self, now: datetime) -> bool:
        if not self.enabled or not (self.text or self.audio):
            return False
        if self.start and now < datetime.fromisoformat(self.start):
            return False
        return not (self.end and now >= datetime.fromisoformat(self.end))

    @property
    def sound(self) -> str:
        """What plays at an approach: the recorded sound, else the text read aloud; "" = nothing (text shown only)."""
        return self.audio or (self.tts_audio if self.text else "")

    def may_play(self, now: datetime, in_call: bool) -> bool:
        """The sound at an approach: within the window, not during a call or a message, once per visit."""
        if in_call or not self.in_window(now) or not self.sound:
            return False
        return not (self.last_played and now - datetime.fromisoformat(self.last_played) < GREETING_PAUSE)

    def next_change(self, now: datetime) -> datetime | None:
        """The next window start or end after `now` (to switch the screen's text exactly then)."""
        times = [datetime.fromisoformat(t) for t in (self.start, self.end) if t]
        later = [t for t in times if t > now]
        return min(later) if later else None


def check_window(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and end <= start:
        raise ValueError("end before start")


@dataclass
class DoorState:
    mute: Mute = field(default_factory=Mute)
    note: Note | None = None
    greeting: Greeting = field(default_factory=Greeting)
    picture: str = ""
    """File name of the door picture under /local/aikos_door; "" = none."""

    def to_dict(self) -> dict[str, Any]:
        return {"mute": asdict(self.mute), "note": asdict(self.note) if self.note else None,
                "greeting": asdict(self.greeting), "picture": self.picture}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "DoorState":
        def part(key: str) -> dict[str, Any]:
            v = d.get(key) if isinstance(d, dict) else None
            if v is not None and not isinstance(v, dict):
                raise TypeError(key)
            return v or {}
        s = cls()
        try:
            s.mute = Mute(**{k: v for k, v in part("mute").items() if k in ("on", "until")})
            note = part("note")
            s.note = Note(**{k: str(note.get(k, "")) for k in ("message", "sender", "since", "voice", "audio")}) if note else None
            s.greeting = Greeting(**{k: v for k, v in part("greeting").items() if k in Greeting.__dataclass_fields__})
            s.picture = str((d or {}).get("picture") or "")
        except (TypeError, ValueError):
            return cls()
        return s
