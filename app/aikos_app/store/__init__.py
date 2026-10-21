"""The app's own small database: accounts, passkeys, sessions, sign-up flows, invites, audit log, push subscriptions.
Nothing else.

Home Assistant data never lands here (rule A16): deleting this database loses accounts and passkeys, never door data.
The database is a single SQLite file on one machine, or an rqlite cluster across the three aikos VMs (backends.py).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from pathlib import Path
from typing import Any, Sequence

from .backends import Backend, DatabaseError, Result, SqliteBackend, Statement, open_backend

__all__ = ["Database", "DatabaseError", "Result", "b64d", "b64e", "new_token", "now", "token_hash"]

SCHEMA_VERSION = 3
SCHEMA_MIN = 2
"""The oldest app schema that can still use a database of SCHEMA_VERSION. Additive changes (new tables or columns the old
code never reads) keep it, so a rollback to the previous image still starts during a rolling update."""

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY,
      handle TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      role TEXT NOT NULL,
      ha_person TEXT NOT NULL DEFAULT '',
      created_at INTEGER NOT NULL,
      disabled_at INTEGER)""",
    """CREATE TABLE IF NOT EXISTS credentials(
      id TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id),
      public_key TEXT NOT NULL,
      sign_count INTEGER NOT NULL,
      transports TEXT NOT NULL DEFAULT '',
      label TEXT NOT NULL DEFAULT '',
      created_at INTEGER NOT NULL,
      last_used_at INTEGER)""",
    """CREATE TABLE IF NOT EXISTS sessions(
      token_hash TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id),
      created_at INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      last_seen_at INTEGER NOT NULL,
      label TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS flows(
      id TEXT PRIMARY KEY,
      kind TEXT NOT NULL,
      challenge TEXT NOT NULL,
      data TEXT NOT NULL DEFAULT '{}',
      expires_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS invites(
      id INTEGER PRIMARY KEY,
      token_hash TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      role TEXT NOT NULL,
      ha_person TEXT NOT NULL DEFAULT '',
      user_id INTEGER REFERENCES users(id),
      created_by INTEGER REFERENCES users(id),
      created_at INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      used_at INTEGER)""",
    """CREATE TABLE IF NOT EXISTS setup_codes(
      code_hash TEXT PRIMARY KEY,
      created_at INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      used_at INTEGER)""",
    """CREATE TABLE IF NOT EXISTS audit(
      id INTEGER PRIMARY KEY,
      ts INTEGER NOT NULL,
      user_id INTEGER,
      action TEXT NOT NULL,
      target TEXT NOT NULL DEFAULT '',
      ok INTEGER NOT NULL,
      ip TEXT NOT NULL DEFAULT '')""",
    # schema 3 (step 2): push; additive, so SCHEMA_MIN stays 2
    """CREATE TABLE IF NOT EXISTS push_subs(
      id INTEGER PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id),
      endpoint TEXT NOT NULL UNIQUE,
      p256dh TEXT NOT NULL,
      auth TEXT NOT NULL,
      label TEXT NOT NULL DEFAULT '',
      created_at INTEGER NOT NULL,
      last_ok_at INTEGER)""",
    "CREATE TABLE IF NOT EXISTS push_sent(key TEXT PRIMARY KEY, at INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS push_subs_user ON push_subs(user_id)",
    "CREATE INDEX IF NOT EXISTS credentials_user ON credentials(user_id)",
    "CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id)",
]

# Schema 1 (step 1, local SQLite only) kept binary values as BLOBs; schema 2 stores them as base64url text so the same
# rows work in rqlite. Columns converted when an old local file is opened:
_V1_BLOBS = {"users": ["handle"], "credentials": ["id", "public_key"], "sessions": ["token_hash"],
             "flows": ["challenge"], "invites": ["token_hash"], "setup_codes": ["code_hash"]}


def now() -> int:
    return int(time.time())


def new_token() -> str:
    """A random secret for links and sessions (256 bit, URL-safe)."""
    return secrets.token_urlsafe(32)


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def token_hash(token: str) -> str:
    """Only hashes of secrets are stored; a stolen database opens no session and no invite."""
    return b64e(hashlib.sha256(token.encode("utf-8")).digest())


class Database:
    def __init__(self, backend: Backend | Path | str) -> None:
        self.backend: Backend = backend if not isinstance(backend, (str, Path)) else open_backend(str(backend))
        self._migrate()

    @classmethod
    def open(cls, url: str = "", user: str = "", password: str = "", ca_file: str = "",
             default_file: Path | None = None) -> "Database":
        return cls(open_backend(url, user, password, ca_file, default_file))

    def _migrate(self) -> None:
        if isinstance(self.backend, SqliteBackend):
            self._migrate_local_v1()
        has_meta = self.backend.query("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'meta'")
        if has_meta:
            row = self.one("SELECT value FROM meta WHERE key = 'schema'")
            version = int(row["value"]) if row else 0
            need = self.one("SELECT value FROM meta WHERE key = 'schema_min'")
            if (int(need["value"]) if need else version) > SCHEMA_VERSION:
                raise DatabaseError(f"database schema {version} is newer than this app ({SCHEMA_VERSION})")
            if version >= SCHEMA_VERSION:
                return  # the same, or newer and still compatible (a rollback): never step a schema back
        self.backend.batch([(sql, ()) for sql in _SCHEMA]
                           + [("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema', ?)", (str(SCHEMA_VERSION),)),
                              ("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_min', ?)", (str(SCHEMA_MIN),))])

    def _migrate_local_v1(self) -> None:
        conn = self.backend.raw()
        if conn.execute("PRAGMA user_version").fetchone()["user_version"] != 1:
            return
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table, cols in _V1_BLOBS.items():
                rows = conn.execute(f"SELECT rowid AS _rid, * FROM {table}").fetchall()
                for r in rows:
                    sets = {c: b64e(r[c]) for c in cols if isinstance(r[c], (bytes, bytearray))}
                    if sets:
                        assign = ", ".join(f"{c} = ?" for c in sets)
                        conn.execute(f"UPDATE {table} SET {assign} WHERE rowid = ?", (*sets.values(), r["_rid"]))
            conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema', '2')")
            conn.execute("PRAGMA user_version = 2")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys = ON")

    def query(self, sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return self.backend.query(sql, args)

    def one(self, sql: str, args: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self.backend.query(sql, args)
        return rows[0] if rows else None

    def execute(self, sql: str, args: Sequence[Any] = ()) -> Result:
        return self.backend.execute(sql, args)

    def batch(self, statements: list[Statement]) -> list[Result]:
        return self.backend.batch(statements)

    def ping(self) -> bool:
        try:
            self.backend.query("SELECT 1 AS ok")
            return True
        except Exception:
            return False

    def close(self) -> None:
        self.backend.close()
