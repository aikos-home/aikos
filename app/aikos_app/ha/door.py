"""Door messages and door status, read from Home Assistant.

Today (step 1) the list comes from Home Assistant's local media folder of the door, enriched by an optional interim source
(the door's proof-of-concept entities: last saved message with seconds/time/recipient, and the recognised text). Step 2
replaces the interim source with the message register of the aikos integration; the public shape below stays.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from .client import HaClient

AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
_STAMP_RE = re.compile(r"(\d{8})-(\d{6})")
INTERIM_HISTORY_DAYS = 30
TEXT_WINDOW_BEFORE_S = 150
TEXT_WINDOW_AFTER_S = 90


@dataclass(frozen=True)
class DoorMessage:
    id: str
    file: str
    content_type: str
    time: str
    """ISO time; from the source if known, else from the file name (local time without zone)."""
    seconds: float | None
    text: str
    recipient: str
    """Name the visitor chose at the door; "" = for everyone."""

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("file")
        d["audio"] = f"/api/v1/door/messages/{self.id}/audio"
        return d


def valid_id(message_id: str) -> bool:
    return bool(_ID_RE.match(message_id)) and ".." not in message_id


def _time_from_name(name: str) -> str:
    m = _STAMP_RE.search(name)
    if not m:
        return ""
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return ""


class DoorMessages:
    def __init__(self, ha: HaClient, settings: Settings) -> None:
        self.ha, self.s = ha, settings

    @property
    def _folder(self) -> str:
        return f"media-source://media_source/local/{self.s.door_media_dir}"

    async def list(self) -> list[DoorMessage]:
        node = await self.ha.command("media_source/browse_media", media_content_id=self._folder)
        files = []
        for child in node.get("children") or []:
            title = child.get("title") or ""
            ext = title[title.rfind("."):].lower() if "." in title else ""
            if child.get("can_expand") or ext not in AUDIO_TYPES:
                continue
            msg_id = title[: -len(ext)]
            if valid_id(msg_id):
                files.append((msg_id, title, AUDIO_TYPES[ext]))
        meta = await self._interim_meta() if self.s.interim_last_message_entity else {}
        out = []
        for msg_id, title, ctype in files:
            m = meta.get(title, {})
            out.append(DoorMessage(id=msg_id, file=title, content_type=ctype,
                                   time=m.get("time") or _time_from_name(title), seconds=m.get("seconds"),
                                   text=m.get("text", ""), recipient=m.get("recipient", "")))
        out.sort(key=lambda d: (d.time, d.id), reverse=True)
        return out

    async def get(self, message_id: str) -> DoorMessage | None:
        if not valid_id(message_id):
            return None
        return next((m for m in await self.list() if m.id == message_id), None)

    async def audio_link(self, message: DoorMessage) -> str:
        """A short-lived signed Home Assistant link; used by the app server only, never handed to a phone."""
        res = await self.ha.command("media_source/resolve_media", media_content_id=f"{self._folder}/{message.file}")
        return res.get("url", "")

    async def _interim_meta(self) -> dict[str, dict[str, Any]]:
        start = (datetime.now(timezone.utc) - timedelta(days=INTERIM_HISTORY_DAYS)).isoformat()
        ids = [e for e in (self.s.interim_last_message_entity, self.s.interim_message_text_entity) if e]
        hist = await self.ha.command("history/history_during_period", start_time=start, entity_ids=ids,
                                     minimal_response=False, no_attributes=False, significant_changes_only=False)
        texts = [(r.get("lu") or r.get("lc") or 0, r.get("s") or "")
                 for r in hist.get(self.s.interim_message_text_entity, [])] if self.s.interim_message_text_entity else []
        meta: dict[str, dict[str, Any]] = {}
        for row in hist.get(self.s.interim_last_message_entity, []):
            name, attrs = row.get("s") or "", row.get("a") or {}
            if name in meta or not name or name in ("unknown", "unavailable"):
                continue
            saved = row.get("lu") or row.get("lc") or 0
            entry: dict[str, Any] = {"time": attrs.get("time") or "", "recipient": attrs.get("recipient") or ""}
            try:
                entry["seconds"] = round(float(attrs.get("seconds")), 1)
            except (TypeError, ValueError):
                pass
            said = _text_of_recording(texts, saved)
            if said:
                entry["text"] = said
            meta[name] = entry
        return meta


def _text_of_recording(texts: list[tuple[float, str]], saved: float) -> str:
    """The recognised text of the recording saved at `saved`: the text entity is cleared ("") when a recording starts
    and grows while words arrive (until a few seconds after saving). So: the last text between the last clear before
    `saved` and the next clear, within the time window."""
    cleared = max((ts for ts, t in texts if t == "" and saved - TEXT_WINDOW_BEFORE_S <= ts <= saved), default=None)
    start = cleared if cleared is not None else saved - TEXT_WINDOW_BEFORE_S
    nxt = min((ts for ts, t in texts if t == "" and ts > saved), default=float("inf"))
    end = min(saved + TEXT_WINDOW_AFTER_S, nxt)
    said = [t for ts, t in sorted(texts) if start <= ts < end and t not in ("", "unknown", "unavailable")]
    return said[-1] if said else ""


@dataclass(frozen=True)
class DoorStatus:
    someone_at_door: bool | None
    someone_since: float | None
    quiet_hours: bool | None
    quiet_start: str
    quiet_end: str
    bell_muted: bool | None


def _on(state: dict[str, Any] | None) -> bool | None:
    if not state or state.get("state") in (None, "unknown", "unavailable"):
        return None
    return state.get("state") == "on"


def door_status(ha: HaClient, s: Settings) -> DoorStatus:
    someone = ha.state(s.entity_someone_at_door)
    quiet = ha.state(s.entity_quiet_hours) or {}
    return DoorStatus(
        someone_at_door=_on(someone),
        someone_since=(someone or {}).get("last_changed"),
        quiet_hours=_on(quiet or None),
        quiet_start=str((quiet.get("attributes") or {}).get("start") or ""),
        quiet_end=str((quiet.get("attributes") or {}).get("end") or ""),
        bell_muted=_on(ha.state(s.entity_bell_muted)),
    )
