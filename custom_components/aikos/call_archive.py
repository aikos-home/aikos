"""The call archive's lines (R23): one JSON object per call start, message and call end. No Home Assistant imports.

The same lines the former package automation wrote, so old and new archive files read alike.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


def _line(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def call_start(now: datetime, test: bool, call_id: str, devices: Iterable[Mapping[str, Any]]) -> str:
    return _line({"type": "call_start", "t": now.isoformat(timespec="seconds"), "test": test, "call_id": call_id,
                  "devices": [{"name": d.get("name"), "model": d.get("model"), "sw": d.get("sw")} for d in devices]})


def call_end(now: datetime, test: bool, call_id: str, duration_s: float) -> str:
    return _line({"type": "call_end", "t": now.isoformat(timespec="seconds"), "test": test, "call_id": call_id,
                  "duration_s": round(duration_s, 1)})


def message(now: datetime, test: bool, call_id: str, in_call: bool, d: Mapping[str, Any]) -> str:
    """A transcript event as an archive line. Visitor text is stored as data, verbatim."""
    return _line({"type": "message", "t": d.get("created", now.isoformat(timespec="seconds")), "test": test,
                  "call_id": call_id if in_call else "", "in_call": in_call, "side": d.get("side", ""),
                  "speaker": d.get("speaker", ""), "role": d.get("speaker_role", ""), "urgent": d.get("urgent", False),
                  "message": d.get("message", ""), "text": d.get("text", ""), "text_original": d.get("text_original", ""),
                  "language": d.get("language", ""), "device": d.get("device", ""), "duration_s": d.get("duration_s"),
                  "transcribe_s": d.get("transcribe_s"), "model": d.get("model", ""), "transcriber": d.get("version", ""),
                  "text_visitor": d.get("text_visitor", ""), "visitor_language": d.get("visitor_language", "")})
