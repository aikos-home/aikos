"""The door message register's rules (aikos-app A10, A15, A27, A38), no Home Assistant code.

A message is one "Nachricht hinterlassen" at the door: the recorder's MP3 in the door's media folder, plus what the door said
around it: whom it is for (the screen's choice), the recognised words and the speaker (door transcripts while recording and
up to TEXT_AFTER_S after it, because the last words arrive late), and who has heard it. Kept until someone deletes it (A27).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any

SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.mp3$")
ADOPT_PREFIX = "nachricht-"          # the recorder's names; other files in the folder (greetings) are no messages
TEXT_AFTER_S = 30                    # words up to this long after the recording ended still belong to it
SAVED_AFTER_S = 120                  # the recorder saves a few seconds after the end (gap, encoding)
RECIPIENT_FRESH_S = 300              # the screen's choice belongs to a message saved within this time
TEXT_MAX = 1000
BY_MAX = 60


def safe_file(name: str) -> bool:
    return bool(SAFE_FILE.match(name or "")) and ".." not in name


@dataclass
class DoorMessage:
    id: str
    file: str
    time: str
    """When it was saved, ISO with zone (an adopted file: its modification time)."""
    seconds: float | None
    recipient: str
    """Whom the visitor chose at the door; "" = for everyone."""
    text: str = ""
    speaker: str = ""
    heard_by: list[str] = field(default_factory=list)
    adopted: bool = False
    """Found in the folder, not told by the recorder (older messages): no text, no recipient known."""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Recording:
    started: datetime
    ended: datetime | None = None
    text: str = ""
    speaker: str = ""
    message_id: str = ""


def _join(before: str, said: str) -> str:
    if not before:
        return said[:TEXT_MAX]
    if said in before:                 # the transcriber repeats a sentence it corrected
        return before
    return f"{before} {said}"[:TEXT_MAX]


class Register:
    """All door messages and the recording in progress. Every method that changes something returns whether it did."""

    def __init__(self) -> None:
        self._messages: dict[str, DoorMessage] = {}
        self._rec: _Recording | None = None
        self._recipient: tuple[str, datetime] | None = None
        self.revision = 0

    # the door
    def recipient_chosen(self, recipient: str, at: datetime) -> None:
        self._recipient = ((recipient or "").strip()[:BY_MAX], at)

    def recording(self, on: bool, at: datetime) -> None:
        if on:
            self._rec = _Recording(started=at)
        elif self._rec is not None and self._rec.ended is None:
            self._rec.ended = at

    def words(self, said: str, speaker: str, at: datetime) -> bool:
        """A door transcript. Counts while recording and shortly after; updates the saved message if it came later."""
        said = (said or "").strip()
        rec = self._rec
        if not said or rec is None or at < rec.started:
            return False
        if rec.ended is not None and (at - rec.ended).total_seconds() > TEXT_AFTER_S:
            return False
        rec.text = _join(rec.text, said)
        rec.speaker = rec.speaker or (speaker or "").strip()[:BY_MAX]
        m = self._messages.get(rec.message_id)
        if m is None or (m.text == rec.text and m.speaker == rec.speaker):
            return False
        m.text, m.speaker = rec.text, rec.speaker
        self.revision += 1
        return True

    def failed(self) -> None:
        self._recipient = None

    def saved(self, file: str, seconds: Any, recipient: str, at: datetime) -> DoorMessage | None:
        """The recorder saved a message. None if the file name is not a plain MP3 name."""
        if not safe_file(file):
            return None
        msg_id = file[:-4]
        try:
            secs: float | None = round(float(seconds), 1)
        except (TypeError, ValueError):
            secs = None
        if msg_id in self._messages:   # told twice: the first stays
            return self._messages[msg_id]
        chosen = self._recipient
        if chosen is not None and (at - chosen[1]).total_seconds() <= RECIPIENT_FRESH_S:
            recipient = chosen[0]
        self._recipient = None
        m = DoorMessage(id=msg_id, file=file, time=at.isoformat(timespec="seconds"), seconds=secs,
                        recipient=(recipient or "").strip()[:BY_MAX])
        rec = self._rec
        if rec is not None and not rec.message_id and (
                rec.ended is None or (at - rec.ended).total_seconds() <= SAVED_AFTER_S):
            rec.message_id = msg_id
            m.text, m.speaker = rec.text, rec.speaker
        self._messages[msg_id] = m
        self.revision += 1
        return m

    def adopt(self, files: dict[str, datetime]) -> int:
        """Files of the recorder in the folder that nobody told the register about (older messages, a missed event)."""
        added = 0
        for name, mtime in files.items():
            if name.startswith(ADOPT_PREFIX) and safe_file(name) and name[:-4] not in self._messages:
                self._messages[name[:-4]] = DoorMessage(id=name[:-4], file=name, time=mtime.isoformat(timespec="seconds"),
                                                        seconds=None, recipient="", adopted=True)
                added += 1
        if added:
            self.revision += 1
        return added

    # the residents (the app decides who may; A15, A38)
    def get(self, msg_id: str) -> DoorMessage | None:
        return self._messages.get(msg_id)

    def remove(self, msg_id: str) -> DoorMessage | None:
        m = self._messages.pop(msg_id, None)
        if m is not None:
            self.revision += 1
        return m

    def heard(self, msg_id: str, by: str) -> bool:
        m = self._messages.get(msg_id)
        by = (by or "").strip()[:BY_MAX]
        if m is None or not by or by in m.heard_by:
            return False
        m.heard_by.append(by)
        self.revision += 1
        return True

    def listing(self) -> list[DoorMessage]:
        """Newest first."""
        return sorted(self._messages.values(), key=lambda m: (m.time, m.id), reverse=True)

    def __len__(self) -> int:
        return len(self._messages)

    # storage
    def to_dict(self) -> dict[str, Any]:
        return {"revision": self.revision, "messages": [m.as_dict() for m in self.listing()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Register":
        r = cls()
        known = {f.name for f in fields(DoorMessage)}
        for d in data.get("messages") or []:
            if isinstance(d, dict) and safe_file(str(d.get("file", ""))) and d.get("id") == str(d["file"])[:-4]:
                m = DoorMessage(**{k: v for k, v in d.items() if k in known})
                m.heard_by = [str(b) for b in m.heard_by or []]
                r._messages[m.id] = m
        r.revision = int(data.get("revision") or 0)
        return r

