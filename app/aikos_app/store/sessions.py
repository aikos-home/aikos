"""Sign-in sessions. The same token works as cookie (PWA) and as bearer token (a later Android app)."""

from __future__ import annotations

from dataclasses import dataclass

from . import Database, new_token, now, token_hash

SESSION_TTL_S = 30 * 24 * 3600
_EXTEND_AFTER_S = 24 * 3600


@dataclass(frozen=True)
class Session:
    user_id: int
    expires_at: int


class Sessions:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, user_id: int, label: str = "") -> str:
        token = new_token()
        t = now()
        self.db.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, label)"
                        " VALUES (?,?,?,?,?,?)", (token_hash(token), user_id, t, t + SESSION_TTL_S, t, label[:120]))
        return token

    def resolve(self, token: str) -> Session | None:
        """The live session for this token; slides the expiry forward at most once a day."""
        if not token:
            return None
        h = token_hash(token)
        row = self.db.one("SELECT s.user_id, s.expires_at, s.last_seen_at FROM sessions s JOIN users u ON u.id = s.user_id"
                          " WHERE s.token_hash = ? AND s.expires_at > ? AND u.disabled_at IS NULL", (h, now()))
        if not row:
            return None
        expires = row["expires_at"]
        if now() - row["last_seen_at"] > _EXTEND_AFTER_S:
            expires = now() + SESSION_TTL_S
            self.db.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                            (now(), expires, h))
        return Session(row["user_id"], expires)

    def revoke(self, token: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))

    def revoke_all(self, user_id: int) -> int:
        return self.db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)).rowcount

    def purge_expired(self) -> None:
        self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))
