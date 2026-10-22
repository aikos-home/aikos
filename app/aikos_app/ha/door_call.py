"""The call at the door as the app shows it live (A47): the aikos integration's call log, `sensor.aikos_call_log` (the
contract the screens use: `call_id`, `active`, `messages_json` = the newest 10, each with `id`, `side` door/room, `who`,
`text`, `tr`, `tr_lang`), and the last ring, `sensor.aikos_door_ring` (aikos 0.15.0). Read only."""

from __future__ import annotations

import json
from typing import Any

from .client import HaClient

CALL_LOG = "sensor.aikos_call_log"
RING = "sensor.aikos_door_ring"
ENTITIES = (CALL_LOG, RING)
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


def call_state(ha: HaClient) -> dict[str, Any]:
    st = ha.state(CALL_LOG) or {}
    a = st.get("attributes") or {}
    return {"active": a.get("active") is True, "call_id": str(a.get("call_id") or ""),
            "messages": _messages(a.get("messages_json")), "ring": ring_time(ha)}
