"""The call at the door as the app shows it live (A47): the aikos integration's call log, `sensor.aikos_call_log` (the
contract the screens use: `call_id`, `active`, `messages_json` = the newest 10, each with `id`, `side` door/room, `who`,
`text`, `tr`, `tr_lang`), the last ring, `sensor.aikos_door_ring` (aikos 0.15.0), and the door's conversation as one
thread that stays after the call, `sensor.aikos_door_thread` (aikos 0.17.0, A49: the chat). Read only."""

from __future__ import annotations

import json
from typing import Any

from .client import HaClient
from .door_actions import VOICE_FILE

CALL_LOG = "sensor.aikos_call_log"
RING = "sensor.aikos_door_ring"
THREAD = "sensor.aikos_door_thread"
ENTITIES = (CALL_LOG, RING, THREAD)
KINDS = ("ring", "door", "room", "reply", "voice", "waiting", "announce", "message")
TEXT_MAX = 600


def _messages(raw: Any) -> list[dict[str, str]]:
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    out = []
    for m in items if isinstance(items, list) else []:
        if not isinstance(m, dict):
            continue
        side = "door" if m.get("side") == "door" else "room"
        out.append({"id": str(m.get("id") or ""), "side": side, "who": str(m.get("who") or "")[:60],
                    "text": str(m.get("text") or "")[:TEXT_MAX], "tr": str(m.get("tr") or "")[:TEXT_MAX],
                    "tr_lang": str(m.get("tr_lang") or "")[:10]})
    return out


def ring_time(ha: HaClient) -> str:
    st = (ha.state(RING) or {}).get("state") or ""
    return "" if st in ("unknown", "unavailable") else st


def thread(ha: HaClient) -> dict[str, Any] | None:
    """The newest visit's entries, oldest first; None without aikos 0.17.0."""
    st = ha.state(THREAD)
    if st is None:
        return None
    a = st.get("attributes") or {}
    visit = a.get("visit")
    out = []
    for e in a.get("entries") or []:
        if not isinstance(e, dict) or e.get("visit") != visit or e.get("kind") not in KINDS:
            continue
        voice = str(e.get("voice") or "")
        seconds = e.get("seconds")
        out.append({"id": str(e.get("id") or ""), "t": str(e.get("t") or ""), "kind": e["kind"],
                    "who": str(e.get("who") or "")[:60], "text": str(e.get("text") or "")[:TEXT_MAX],
                    "spoken": e.get("spoken") if isinstance(e.get("spoken"), bool) else None,
                    "voice": voice if VOICE_FILE.match(voice) else "",
                    "seconds": round(float(seconds), 1) if isinstance(seconds, (int, float)) else None})
    return {"visit": visit, "entries": out}


def call_state(ha: HaClient) -> dict[str, Any]:
    st = ha.state(CALL_LOG) or {}
    a = st.get("attributes") or {}
    return {"active": a.get("active") is True, "call_id": str(a.get("call_id") or ""),
            "messages": _messages(a.get("messages_json")), "ring": ring_time(ha), "thread": thread(ha)}
