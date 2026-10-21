"""Pending passkey ceremonies. Each challenge is stored server-side and can be consumed exactly once (no replay)."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass

from . import Database, b64d, b64e, now

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
        self.db.batch([("DELETE FROM flows WHERE expires_at <= ?", (now(),)),
                       ("INSERT INTO flows(id, kind, challenge, data, expires_at) VALUES (?, ?, ?, ?, ?)",
                        (flow_id, kind, b64e(challenge), json.dumps(data or {}), now() + FLOW_TTL_S))])
        return flow_id

    def take(self, flow_id: str, kind: str) -> Flow | None:
        """Returns the flow and deletes it; whoever deletes the row owns it, so a second call gets None."""
        row = self.db.one("SELECT * FROM flows WHERE id = ? AND kind = ? AND expires_at > ?", (flow_id, kind, now()))
        if not row:
            return None
        if self.db.execute("DELETE FROM flows WHERE id = ? AND kind = ?", (flow_id, kind)).rowcount != 1:
            return None
        return Flow(row["id"], row["kind"], b64d(row["challenge"]), json.loads(row["data"]))
