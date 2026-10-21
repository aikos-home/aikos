"""Heartbeat of the transcriber for a push monitor (Uptime Kuma): one check per run; launchd runs it every 30 s.

    python -m aikos_transcriber.heartbeat [--dry-run] [--env FILE]   # settings from the environment, like the receivers

"up" only if both receivers listen (UDP 5006 + 5008), Whisper is ready and Home Assistant answers with the transcriber's
token. Otherwise "down" with the reasons; those also go to stdout (the agent's log), as do retried connections.

- Busy is not dead: Whisper is asked for /health, which whisper-server answers outside its inference lock, so a running
  transcription never reads as down (measured 21.10.2026: < 1 ms while transcribing). 503 = the model is still loading.
- A connection that doesn't open (or doesn't answer) within 4 s is tried once more on a new connection, i.e. from a new
  local port; only a second miss counts. A refused connection counts at once: nothing listens there.
- The Mac itself: macOS keeps TCP time in milliseconds in 32 bits. After 49.7 days of uptime it wraps, TIME_WAIT never
  ends any more, and a connect from a local port the server still holds in TIME_WAIT hangs; the ports run out after a day
  or two. That is reported as what it is, a Mac that needs a restart, not as a dead Whisper (20./21.10.2026: 41 false
  "whisper down" in 20 h). From 45 days of uptime on, the "up" message names the time by which to restart.

    AIKOS_HEARTBEAT_URL         push URL without the token, e.g. https://status.example.org/api/push   (required)
    AIKOS_HEARTBEAT_TOKEN_FILE  file with the push token, mode 600                                     (required)
    AIKOS_HA_URL, AIKOS_HA_TOKEN_FILE, AIKOS_WHISPER_URL   as for the receivers (config.py)

The push token never appears in the output.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import Config

PORTS = (5006, 5008)               # room, door: the receivers' defaults (AIKOS_PORT is set per side, never shared)
TIMEOUT_S = 4.0
TCP_WRAP_S = 2 ** 32 / 1000        # macOS tcp_now: milliseconds in 32 bits, wraps after 49.7 days of uptime
WARN_S = 45 * 86400                # from here on the "up" message says by when to restart
WRAPPED_WAITS = 1000               # after the wrap, this many TIME_WAIT show that they no longer end (healthy: a few hundred)
PORTS_LOW_WAITS = 8192             # half of macOS' 16,384 ephemeral ports stuck in TIME_WAIT, whatever the uptime


class Missed(Exception):
    """No HTTP answer: "refused" (nothing listens), "stalled" (no connection or no reply in time) or another reason."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def get(url: str, headers: dict | None = None, timeout: float = TIMEOUT_S) -> int:
    """HTTP status of one GET on a new connection; Missed without an answer."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            raise Missed("refused") from None
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise Missed("stalled") from None
        raise Missed(str(exc.reason)) from None
    except (socket.timeout, TimeoutError):
        raise Missed("stalled") from None
    except OSError as exc:                                               # e.g. reset while reading the reply
        raise Missed(exc.strerror or type(exc).__name__) from None


def answer(url: str, headers: dict | None = None, http=None) -> tuple[int | None, str, bool]:
    """(status or None, why not, retried): a stalled connection is tried once more on a new one before it counts."""
    http = http or get
    try:
        return http(url, headers), "", False
    except Missed as m:
        if m.why != "stalled":
            return None, m.why, False
    try:
        return http(url, headers), "", True
    except Missed as m:
        return None, m.why, True


def health_url(whisper_url: str) -> str:
    u = urllib.parse.urlsplit(whisper_url)
    return f"{u.scheme}://{u.netloc}/health"


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def listening(ports=PORTS) -> int:
    """How many of the ports have a UDP listener. lsof exits 1 on mere warnings (an SMB mount): only its output counts."""
    return sum(len(_run(["lsof", "-nP", f"-iUDP:{p}"]).splitlines()) > 1 for p in ports)


def boot_time() -> float | None:
    """When this Mac started (Unix time); None elsewhere or if unknown. Only macOS has the 49.7-day wrap."""
    if sys.platform != "darwin":
        return None
    m = re.search(r"\bsec = (\d+)", _run(["sysctl", "-n", "kern.boottime"]))
    return float(m.group(1)) if m else None


def time_waits() -> int | None:
    out = _run(["netstat", "-an", "-p", "tcp"])
    return sum(line.rstrip().endswith("TIME_WAIT") for line in out.splitlines()) if out else None


def check(env, http=None, receivers=None, booted=None, waits=None, now: float | None = None):
    """(status "up" | "down", message for the monitor, notes worth a log line even when up). The probes default to the
    real ones (looked up at call time)."""
    http, receivers, booted, waits = http or get, receivers or listening, booted or boot_time, waits or time_waits
    now = time.time() if now is None else now
    problems: list[str] = []
    notes: list[str] = []
    n = receivers()
    if n < len(PORTS):
        problems.append(f"receivers {n}/{len(PORTS)}")

    code, why, retried = answer(health_url(env.get("AIKOS_WHISPER_URL") or Config.whisper_url), http=http)
    if code == 200:
        if retried:
            notes.append("whisper: the first connection stalled, the second answered")
    elif code == 503:
        problems.append("whisper loading model")
    elif code is None:
        problems.append("whisper down (refused)" if why == "refused" else
                        f"whisper not answering ({why}{', 2 tries' if retried else ''})")
    else:
        problems.append(f"whisper HTTP {code}")

    try:
        token = Path(env.get("AIKOS_HA_TOKEN_FILE", "")).read_text().strip()
    except OSError:
        token = None
    if token is None:
        problems.append("HA token file not readable")
    else:
        code, why, retried = answer(env.get("AIKOS_HA_URL", "").rstrip("/") + "/api/", {"Authorization": f"Bearer {token}"},
                                    http=http)
        if code is None:
            problems.append(f"HA not answering ({why}{', 2 tries' if retried else ''})")
        elif code != 200:
            problems.append(f"HA {code}")
        elif retried:
            notes.append("HA: the first connection stalled, the second answered")

    due = ""
    boot = booted()
    w = waits() if boot is not None else None
    if boot is not None and now - boot >= TCP_WRAP_S and (w is None or w >= WRAPPED_WAITS):
        problems.insert(0, f"Mac restart needed: up {(now - boot) / 86400:.1f} d, macOS TCP clock wrapped at 49.7 d, "
                           "TIME_WAIT never ends" + (f" ({w} now)" if w is not None else ""))
    elif w is not None and w >= PORTS_LOW_WAITS:
        problems.insert(0, f"TCP ports running out: {w} TIME_WAIT")
    elif boot is not None and now - boot >= WARN_S:
        due = dt.datetime.fromtimestamp(boot + TCP_WRAP_S).strftime("%Y-%m-%d %H:%M")
    if problems:
        return "down", "; ".join(problems), notes
    return "up", "ok" + (f"; restart the Mac before {due} (macOS TCP clock, 49.7 d)" if due else ""), notes


def push(base: str, token: str, status: str, msg: str, opener=urllib.request.urlopen) -> None:
    """Uptime Kuma push: GET <base>/<token>?status=&msg=&ping=, one retry. Errors never carry the URL (it holds the token)."""
    url = f"{base.rstrip('/')}/{urllib.parse.quote(token, safe='')}?" + urllib.parse.urlencode(
        {"status": status, "msg": msg, "ping": ""})
    for attempt in (1, 2):
        try:
            with opener(url, timeout=8) as r:
                r.read()
            return
        except Exception as exc:                                         # noqa: BLE001
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            if attempt == 2:
                code = getattr(exc, "code", None)
                raise RuntimeError(f"push failed: {type(exc).__name__}" + (f" {code}" if code else "")) from None
            time.sleep(2)


def settings_file(path: Path) -> dict:
    """The house settings (KEY=value per line, "#" = comment), as deploy/launchd.py hands them to the agents."""
    env = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            env[key.strip()] = value.strip()
    return env


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the result, push nothing")
    ap.add_argument("--env", type=Path, help="read the settings from this file (deploy.sh), not from the environment")
    a = ap.parse_args(argv)
    env = {**os.environ, **settings_file(a.env.expanduser())} if a.env else os.environ
    needed = ("AIKOS_HA_URL", "AIKOS_HA_TOKEN_FILE") + (() if a.dry_run else ("AIKOS_HEARTBEAT_URL", "AIKOS_HEARTBEAT_TOKEN_FILE"))
    missing = [k for k in needed if not env.get(k)]
    if missing:
        print(f"missing settings: {', '.join(missing)}", file=sys.stderr)
        return 2
    status, msg, notes = check(env)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    for note in notes:
        print(f"{stamp} note: {note}", flush=True)
    if a.dry_run:
        print(f"{status}: {msg}", flush=True)
        return 0
    if status != "up":
        print(f"{stamp} down: {msg}", flush=True)
    try:
        token = Path(env["AIKOS_HEARTBEAT_TOKEN_FILE"]).read_text().strip()
        push(env["AIKOS_HEARTBEAT_URL"], token, status, msg)
    except (OSError, RuntimeError) as exc:
        print(f"{stamp} {exc if isinstance(exc, RuntimeError) else 'push token file not readable'}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
