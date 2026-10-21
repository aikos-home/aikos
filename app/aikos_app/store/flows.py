"""Pending passkey ceremonies. Each challenge is stored server-side and can be consumed exactly once (no replay)."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass

from . import Database, now

FLOW_TTL_S = 5 * 60


@dataclass(frozen=True)
class Flow:
    id: str
    kind: str
    challenge: bytes
    data: dict


class Flows:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(self, kind: str, challenge: bytes, data: dict | None = None) -> str:
        flow_id = secrets.token_urlsafe(16)
        self.db.execute("DELETE FROM flows WHERE expires_at <= ?", (now(),))
        self.db.execute("INSERT INTO flows(id, kind, challenge, data, expires_at) VALUES (?,?,?,?,?)",
                        (flow_id, kind, challenge, json.dumps(data or {}), now() + FLOW_TTL_S))
        return flow_id

    def take(self, flow_id: str, kind: str) -> Flow | None:
        """Returns the flow and deletes it in one step; a second call with the same id gets None."""
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM flows WHERE id = ? AND kind = ? AND expires_at > ?",
                            (flow_id, kind, now())).fetchone()
            c.execute("DELETE FROM flows WHERE id = ?", (flow_id,))
        if not row:
            return None
        return Flow(row["id"], row["kind"], row["challenge"], json.loads(row["data"]))
