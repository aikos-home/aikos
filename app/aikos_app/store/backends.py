"""Where the app's small database lives: one SQLite file (one machine) or an rqlite cluster (three VMs).

Both offer the same narrow interface: query, execute, and an atomic batch of statements. There are no interactive
transactions (rqlite has none), so every rule that needs atomicity is written as one statement or one batch.
Binary values are stored as base64url text by the callers, so both backends only see text, numbers and NULL.
"""

from __future__ import annotations

import base64
import http.client
import json
import sqlite3
import ssl
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence
from urllib.parse import urlsplit

Statement = tuple[str, Sequence[Any]]
TIMEOUT_S = 5.0


class DatabaseError(Exception):
    pass


@dataclass(frozen=True)
class Result:
    rowcount: int
    lastrowid: int | None


class Backend(Protocol):
    def query(self, sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]: ...

    def execute(self, sql: str, args: Sequence[Any] = ()) -> Result: ...

    def batch(self, statements: list[Statement]) -> list[Result]: ...

    def close(self) -> None: ...


class SqliteBackend:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = lambda cur, row: {d[0]: v for d, v in zip(cur.description, row)}
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()

    def query(self, sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return self._conn.execute(sql, tuple(args)).fetchall()

    def execute(self, sql: str, args: Sequence[Any] = ()) -> Result:
        with self._lock:
            cur = self._conn.execute(sql, tuple(args))
            return Result(cur.rowcount, cur.lastrowid)

    def batch(self, statements: list[Statement]) -> list[Result]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                out = []
                for sql, args in statements:
                    cur = self._conn.execute(sql, tuple(args))
                    out.append(Result(cur.rowcount, cur.lastrowid))
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")
            return out

    def raw(self) -> sqlite3.Connection:
        """Only for the one-time migration of an old local file."""
        return self._conn

    def close(self) -> None:
        self._conn.close()


class RqliteBackend:
    """rqlite over its HTTP API. Writes go to any node (it forwards to the leader); on a connection error the next
    node in the list is tried. HTTPS with a CA file and basic auth: the database travels over the house network."""

    def __init__(self, nodes: list[str], user: str = "", password: str = "", ca_file: str = "",
                 timeout: float = TIMEOUT_S) -> None:
        if not nodes:
            raise DatabaseError("no rqlite nodes")
        self._nodes = nodes
        self._auth = ("Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()) if user else ""
        self._ssl = ssl.create_default_context(cafile=ca_file or None)
        self._timeout = timeout
        self._local = threading.local()
        self._lock = threading.Lock()

    def _conn(self, node: str) -> http.client.HTTPConnection:
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = self._local.conns = {}
        if node not in conns:
            u = urlsplit(node)
            if u.scheme == "https":
                conns[node] = http.client.HTTPSConnection(u.hostname, u.port or 4001, timeout=self._timeout,
                                                          context=self._ssl)
            else:
                conns[node] = http.client.HTTPConnection(u.hostname, u.port or 4001, timeout=self._timeout)
        return conns[node]

    def _post(self, path: str, body: Any) -> dict[str, Any]:
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if self._auth:
            headers["Authorization"] = self._auth
        last: Exception | None = None
        for node in self._nodes:
            conn = self._conn(node)
            try:
                conn.request("POST", path, payload, headers)
                resp = conn.getresponse()
                data = resp.read()
            except (OSError, http.client.HTTPException) as e:
                conn.close()
                self._local.conns.pop(node, None)
                last = e
                continue
            if resp.status != 200:
                raise DatabaseError(f"rqlite {resp.status}: {data[:200]!r}")
            return json.loads(data)
        raise DatabaseError(f"no rqlite node reachable: {last}")

    @staticmethod
    def _check(result: dict[str, Any]) -> dict[str, Any]:
        if "error" in result:
            raise DatabaseError(result["error"])
        return result

    def query(self, sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        res = self._post("/db/query?associative&level=weak", [[sql, *args]])
        return self._check(res["results"][0]).get("rows") or []

    def execute(self, sql: str, args: Sequence[Any] = ()) -> Result:
        return self.batch([(sql, args)])[0]

    def batch(self, statements: list[Statement]) -> list[Result]:
        res = self._post("/db/execute?transaction", [[sql, *args] for sql, args in statements])
        out = []
        for r in res["results"]:
            self._check(r)
            out.append(Result(int(r.get("rows_affected", 0)), r.get("last_insert_id")))
        return out

    def close(self) -> None:
        for conn in getattr(self._local, "conns", {}).values():
            conn.close()


def open_backend(url: str, user: str = "", password: str = "", ca_file: str = "", default_file: Path | None = None):
    """`rqlite://a:4001,b:4001` (HTTP), `rqlites://…` (HTTPS) or a file path / `sqlite:///path`; empty = default file."""
    if url.startswith(("rqlite://", "rqlites://")):
        scheme = "https" if url.startswith("rqlites://") else "http"
        hosts = url.split("://", 1)[1].strip("/").split(",")
        return RqliteBackend([f"{scheme}://{h}" for h in hosts if h], user, password, ca_file)
    path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else url
    return SqliteBackend(path or default_file)
