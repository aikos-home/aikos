"""The call log: how transcripts become the chat both screens show. No Home Assistant imports.

R22: the log is emptied when a call starts and when it ends; a transcript outside a call is not added.
R25: a visitor's identity holds for the rest of the call (later door messages without a speaker keep it, marked `sticky`).
R26: the same per room key: a resident's name sticks to the key that said it, never to another key.
R27: devices get only the newest 10 messages (`feed_json`); the log keeps up to 20.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

KEEP = 20
FEED = 10
TEXT_MAX = 300
INVALID = ("unknown", "unavailable", "")


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


@dataclass
class CallLog:
    messages: list[dict[str, Any]] = field(default_factory=list)
    call_id: str = ""

    def start(self, call_id: str) -> None:
        self.messages = []
        self.call_id = call_id

    def end(self) -> None:
        self.messages = []                           # the call_id stays until the next call starts

    def add(self, side: str, stamp: str, attrs: Mapping[str, Any]) -> bool:
        """Add (or replace, same transcript) one message. Returns False if the transcript is not valid."""
        if stamp in INVALID:
            return False
        spk = attrs.get("speaker") or ""
        dev = (attrs.get("device") or "") if side == "room" else ""
        msg_id = f"{side}-{stamp}"
        known_who, known_role = "", ""
        for m in self.messages:                      # the last identity this source said itself in this call
            if m["side"] == side and m.get("dev", "") == dev and m.get("spk") and m["id"] != msg_id:
                known_who, known_role = m["who"], m["role"]
        sticky = not spk and known_who != ""
        who = spk or (known_who if sticky else ("Besucher" if side == "door" else (dev or "Bewohner")))
        language = attrs.get("language")
        entry = {
            "id": msg_id, "t": stamp, "side": side, "who": who,
            "role": attrs.get("speaker_role") or (known_role if sticky else ""),
            "text": (attrs.get("message") or attrs.get("text") or "")[:TEXT_MAX],
            "urgent": _bool(attrs.get("urgent", False)),
            "lang": (attrs.get("language_name") or "") if (language and language != "de") else "",
            "spk": spk, "dev": dev, "sticky": sticky,
        }
        for i, m in enumerate(self.messages):
            if m["id"] == msg_id:
                self.messages[i] = entry
                break
        else:
            self.messages.append(entry)
        self.messages = self.messages[-KEEP:]
        return True

    @property
    def last_id(self) -> str:
        return self.messages[-1]["id"] if self.messages else ""

    @property
    def last_time(self) -> str | None:
        return self.messages[-1]["t"] if self.messages else None

    def feed_json(self) -> str:
        """The newest 10 messages, oldest first, as compact JSON text (ESPHome reads attributes as text)."""
        return json.dumps(self.messages[-FEED:], ensure_ascii=False, separators=(",", ":"))
