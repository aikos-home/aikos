#!/usr/bin/env python3
"""Push heartbeats for the house monitor (Uptime Kuma), every 30 s (systemd timer). Standard library only.

Two monitors, as agreed with the house infrastructure:
- per node (`KUMA_NODE_URL`): "this node carries"; up while the app answers healthy.
- the service (`KUMA_VIP_URL`): sent only by the node that holds the virtual address, after checking the domain on it.
  No holder, no beat: then the monitor alerts, which is right.

Never `down` for a node that is busy or in its own rollout (the rollout agent writes /run/aikos/rollout while it works):
the beat is simply skipped, and a short rollout stays inside the monitor's window. A node that is really broken sends
`down` with the reason. Push URLs (they contain tokens) live in /etc/aikos/secrets/kuma.env; without it, nothing is sent.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path("/etc/aikos/secrets/kuma.env")
ROLLOUT_FLAG = Path("/run/aikos/rollout")
HEALTH = "http://127.0.0.1:8780/api/v1/health"


def get(url: str, timeout: float = 3.0, context=None) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {}
    except (OSError, ValueError):
        return 0, {}


def node_verdict(status: int, body: dict, rolling: bool) -> tuple[str, str] | None:
    """('up'|'down', message) or None = skip this beat."""
    if status == 200 and body.get("ok"):
        return "up", f"ok {body.get('commit', '')[:12]}" + ("" if body.get("ha_connected") else ", HA away")
    if rolling:
        return None
    if status == 0:
        return "down", "app does not answer"
    return "down", "database not reachable" if body.get("db") is False else f"health {status}"


def holds_vip(vip: str) -> bool:
    out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True).stdout
    return f" {vip}/" in out


def push(url: str, status: str, msg: str, ping_ms: int) -> None:
    q = urllib.parse.urlencode({"status": status, "msg": msg[:80], "ping": ping_ms})
    urllib.request.urlopen(url.split("?")[0] + "?" + q, timeout=5).read()


class _ViaAddress(http.client.HTTPSConnection):
    """HTTPS to a given address while naming the domain (SNI and Host), like a phone resolving it to that address."""

    def __init__(self, address: str, domain: str, context: ssl.SSLContext, timeout: float) -> None:
        super().__init__(address, 443, context=context, timeout=timeout)
        self._domain = domain

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._domain)


def service_ok(vip: str, domain: str) -> bool:
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE  # Caddy's own CA until the public certificate
    conn = _ViaAddress(vip, domain, ctx, 3.0)
    try:
        conn.request("GET", "/api/v1/health", headers={"Host": domain})
        r = conn.getresponse()
        return r.status == 200 and bool(json.loads(r.read()).get("ok"))
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def main() -> int:
    if not SECRETS.exists():
        return 0
    cfg = dict(line.split("=", 1) for line in SECRETS.read_text(encoding="utf-8").split() if "=" in line)
    t0 = time.monotonic()
    status, body = get(HEALTH)
    ms = int((time.monotonic() - t0) * 1000)
    verdict = node_verdict(status, body, ROLLOUT_FLAG.exists())
    if verdict and cfg.get("KUMA_NODE_URL"):
        push(cfg["KUMA_NODE_URL"], *verdict, ms)
    vip, domain = os.environ.get("VIP", ""), os.environ.get("DOMAIN", "")
    if cfg.get("KUMA_VIP_URL") and vip and holds_vip(vip):
        t0 = time.monotonic()
        ok = service_ok(vip, domain)
        push(cfg["KUMA_VIP_URL"], "up" if ok else "down", "service ok" if ok else "domain on the virtual address fails",
             int((time.monotonic() - t0) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
