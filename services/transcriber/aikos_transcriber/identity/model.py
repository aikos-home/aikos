"""Result types.

Part of the aikos transcriber (split from roomkey tools/talk_identity.py at d0d52b9, code unchanged).
"Who is speaking" logic: the roomkey maintainers have the say here (review required)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Identity:
    speaker: str = ""   # display text: "Jonas", "Paketdienst · DHL", "Polizei", "" = nobody introduced themselves
    kind: str = ""      # "name" | "role" | ""
    name: str = ""      # personal name as said, or ""
    role: str = ""      # role id from ROLES, or ""
    org: str = ""       # company, or ""
    message: str = ""   # transcript without greeting + self-introduction ("" if nothing else was said)
    method: str = ""    # "rules" | "llm" | ""
    urgent: bool = False  # somebody needs help (R17.15)
    vtype: str = ""     # visitor type id for the RoomKey icon (role, "family", "name", content type, "emergency", "")


@dataclass
class _Who:
    name: str
    rid: str
    org: str
    matched: str
    end: int
