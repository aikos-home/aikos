"""Audit log: who did what, when, and whether it was allowed. Never stores message text or secrets."""

from __future__ import annotations

from . import Database, now


class Audit:
    def __init__(self, db: Database) -> None:
        self.db = db

    def log(self, action: str, ok: bool, user_id: int | None = None, target: str = "", ip: str = "") -> None:
        self.db.execute("INSERT INTO audit(ts, user_id, action, target, ok, ip) VALUES (?,?,?,?,?,?)",
                        (now(), user_id, action, target[:200], 1 if ok else 0, ip[:64]))

    def recent(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]
