"""The app's own small database (SQLite): accounts, passkeys, sessions, sign-up flows, invites, audit log. Nothing else.

Home Assistant data never lands here (rule A16): deleting this database loses accounts and passkeys, never door data.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE users(
  id INTEGER PRIMARY KEY,
  handle BLOB NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  ha_person TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  disabled_at INTEGER
);
CREATE TABLE credentials(
  id BLOB PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  public_key BLOB NOT NULL,
  sign_count INTEGER NOT NULL,
  transports TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  last_used_at INTEGER
);
CREATE TABLE sessions(
  token_hash BLOB PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  label TEXT NOT NULL DEFAULT ''
);
CREATE TABLE flows(
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  challenge BLOB NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  expires_at INTEGER NOT NULL
);
CREATE TABLE invites(
  id INTEGER PRIMARY KEY,
  token_hash BLOB NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  ha_person TEXT NOT NULL DEFAULT '',
  user_id INTEGER REFERENCES users(id),
  created_by INTEGER REFERENCES users(id),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at INTEGER
);
CREATE TABLE setup_codes(
  code_hash BLOB PRIMARY KEY,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at INTEGER
);
CREATE TABLE audit(
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  user_id INTEGER,
  action TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '',
  ok INTEGER NOT NULL,
  ip TEXT NOT NULL DEFAULT ''
);
"""


def now() -> int:
    return int(time.time())


def new_token() -> str:
    """A random secret for links and sessions (256 bit, URL-safe)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    """Only hashes of secrets are stored; a stolen database opens no session and no invite."""
    return hashlib.sha256(token.encode("utf-8")).digest()


class Database:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"database schema {version} is newer than this app ({SCHEMA_VERSION})")
        if version < 1:
            # executescript commits on its own, so the transaction is part of the script
            with self._lock:
                self._conn.executescript(f"BEGIN;\n{_SCHEMA_V1}\nPRAGMA user_version = 1;\nCOMMIT;")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def execute(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, args)

    def close(self) -> None:
        self._conn.close()
