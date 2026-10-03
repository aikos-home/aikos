"""The call log: how transcripts become the chat both screens show. No Home Assistant imports.

R22: the log is emptied when a call starts and when it ends; a transcript outside a call is not added.
R25: a visitor's identity holds for the rest of the call (later door messages without a speaker keep it, marked `sticky`).
R26: the same per room key: a resident's name sticks to the key that said it, never to another key.
R27: devices get only the newest 10 messages (`feed_json`); the log keeps up to 20.
R28: the visitor's language holds for the call once a door sentence is clearly in it (`visitor_language`); a resident's
message carries its translation for the door screen (`tr`, `tr_lang`) when the transcriber sent one.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

KEEP = 20
# R28: a door sentence sets the call's visitor language only when Whisper is this sure and it has this many words
# (a short noise taken for Dutch must not switch the call).
VISITOR_MIN_P = 0.8
VISITOR_MIN_WORDS = 3
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
    visitor_language: str = ""                       # "" = German (or not known yet)
    visitor_language_name: str = ""

    def start(self, call_id: str) -> None:
        self.messages = []
        self.call_id = call_id
        self.visitor_language = self.visitor_language_name = ""

    def end(self) -> None:
        self.messages = []                           # the call_id stays until the next call starts
        self.visitor_language = self.visitor_language_name = ""

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
        if side == "room" and attrs.get("text_visitor"):
            entry["tr"] = str(attrs["text_visitor"])[:TEXT_MAX]
            entry["tr_lang"] = attrs.get("visitor_language") or ""
        if side == "door":
            self._visitor_language(attrs)
        for i, m in enumerate(self.messages):
            if m["id"] == msg_id:
                self.messages[i] = entry
                break
        else:
            self.messages.append(entry)
        self.messages = self.messages[-KEEP:]
        return True

    def _visitor_language(self, attrs: Mapping[str, Any]) -> None:
        lang = attrs.get("language") or ""
        try:
            sure = float(attrs.get("language_probability") or 0) >= VISITOR_MIN_P
        except (TypeError, ValueError):
            sure = False
        said = (attrs.get("text") if lang == "de" else attrs.get("text_original")) or ""
        if not lang or not sure or len(said.split()) < VISITOR_MIN_WORDS:
            return
        if lang == "de":
            self.visitor_language = self.visitor_language_name = ""
        else:
            self.visitor_language, self.visitor_language_name = lang, attrs.get("language_name") or lang

    @property
    def last_id(self) -> str:
        return self.messages[-1]["id"] if self.messages else ""

    @property
    def last_time(self) -> str | None:
        return self.messages[-1]["t"] if self.messages else None

    def feed_json(self) -> str:
        """The newest 10 messages, oldest first, as compact JSON text (ESPHome reads attributes as text)."""
        return json.dumps(self.messages[-FEED:], ensure_ascii=False, separators=(",", ":"))
