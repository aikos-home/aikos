#!/usr/bin/env python3
"""Hourly, consistent copy of the app database for the house backup (passkeys cannot be recovered otherwise).

Asks rqlite for a backup over its API (never copies files of a running database), checks the copy with SQLite's
integrity check, then replaces /var/backups/aikos/aikos-app.sqlite atomically and writes its SHA-256 and `last-ok`.
"""

from __future__ import annotations

import base64
import grp
import hashlib
import json
import os
import sqlite3
import ssl
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(os.environ.get("AIKOS_BACKUP_DIR", "/var/backups/aikos"))


def main() -> int:
    secrets = dict(line.split("=", 1) for line in
                   Path("/etc/aikos/secrets/backup.env").read_text(encoding="utf-8").split() if "=" in line)
    node = os.environ["NODE_IP"]
    auth = base64.b64encode(f"{secrets['DB_USER']}:{secrets['DB_PASSWORD']}".encode()).decode()
    req = urllib.request.Request(f"https://{node}:4001/db/backup", headers={"Authorization": "Basic " + auth})
    ctx = ssl.create_default_context(cafile="/etc/aikos/certs/ca.crt")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "aikos-app.sqlite.tmp"
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    os.chmod(tmp, 0o600)
    con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("backup failed the integrity check")
        has_users = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0] if has_users else 0
    finally:
        con.close()
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    try:  # the house backup reads it as the `aikos` group, nobody else
        os.chown(tmp, 0, grp.getgrnam("aikos").gr_gid)
        os.chmod(tmp, 0o640)
    except KeyError:
        pass
    tmp.replace(OUT / "aikos-app.sqlite")
    (OUT / "aikos-app.sqlite.sha256").write_text(f"{digest}  aikos-app.sqlite\n", encoding="utf-8")
    (OUT / "last-ok").write_text(json.dumps({"time": int(time.time()), "users": users}) + "\n", encoding="utf-8")
    print(f"backup ok: {users} people, sha256 {digest[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
