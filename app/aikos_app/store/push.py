"""Push subscriptions (one per phone and browser), the app's VAPID key, and "already pushed" markers.

The VAPID key is created once and shared by every node through the database (one statement, so the nodes agree). The
markers make sure that of three nodes seeing the same new message only one sends the push.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import Database, now

KEEP_SENT_S = 30 * 86400


@dataclass(frozen=True)
class Subscription:
    id: int
    user_id: int
    endpoint: str
    p256dh: str
    auth: str
    label: str


class Pushes:
    def __init__(self, db: Database) -> None:
        self.db = db

    def vapid_private(self, new_key: str) -> str:
        """The stored key; `new_key` is stored if there is none yet (the first node wins, the others read it)."""
        self.db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('vapid_private', ?)", (new_key,))
        return self.db.one("SELECT value FROM meta WHERE key = 'vapid_private'")["value"]

    def subscribe(self, user_id: int, endpoint: str, p256dh: str, auth: str, label: str) -> None:
        """The same phone again (same endpoint) updates its keys; under another person it moves to them."""
        self.db.execute(
            "INSERT INTO push_subs(user_id, endpoint, p256dh, auth, label, created_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh,"
            " auth = excluded.auth, label = excluded.label",
            (user_id, endpoint, p256dh, auth, label[:80], now()))

    def unsubscribe(self, user_id: int, endpoint: str) -> bool:
        return self.db.execute("DELETE FROM push_subs WHERE user_id = ? AND endpoint = ?", (user_id, endpoint)).rowcount > 0

    def gone(self, endpoint: str) -> None:
        """The push service says the subscription no longer exists."""
        self.db.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))

    def delivered(self, endpoint: str) -> None:
        self.db.execute("UPDATE push_subs SET last_ok_at = ? WHERE endpoint = ?", (now(), endpoint))

    def of_user(self, user_id: int) -> list[Subscription]:
        rows = self.db.query("SELECT s.* FROM push_subs s JOIN users u ON u.id = s.user_id"
                             " WHERE s.user_id = ? AND u.disabled_at IS NULL ORDER BY s.id", (user_id,))
        return [Subscription(r["id"], r["user_id"], r["endpoint"], r["p256dh"], r["auth"], r["label"]) for r in rows]

    def claim(self, key: str) -> bool:
        """True for exactly one caller per key, across all nodes."""
        t = now()
        res = self.db.batch([("DELETE FROM push_sent WHERE at < ?", (t - KEEP_SENT_S,)),
                             ("INSERT OR IGNORE INTO push_sent(key, at) VALUES (?, ?)", (key, t))])
        return res[1].rowcount == 1
