"""The heartbeat (the same contract as the transcriber's): every INTERVAL the service asks whether the Whisper that checks
every sentence answers, and pushes to the house monitor (Uptime Kuma, its push URL in a file with 0600 outside the repo).
"up" only while the model is loaded (it is, while this runs) and the check answers: without the check nothing is said. The
message names the cause. The answer is kept for the health endpoint, which therefore never waits for Whisper.

Through the aikos hub (AIKOS_TTS_WHISPER_URL = http://<hub>/c/<client>, AIKOS_TTS_WHISPER_BACKEND = the hub's name for
the Whisper it routes this client to): the hub's own status says whether that backend is up; its paths other than the
transcription would reach another backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_LOGGER = logging.getLogger(__name__)
INTERVAL = 30
TIMEOUT = 5
OK, UNREACHABLE, OFF = "ok", "unreachable", "off"


def hub_state(url: str, backend: str) -> str:
    """The hub's status of the backend that does this client's transcriptions."""
    parts = urllib.parse.urlsplit(url)
    status = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/hub/v1/status", "", ""))
    try:
        with urllib.request.urlopen(status, timeout=TIMEOUT) as r:
            backends = json.loads(r.read()).get("backends") or {}
    except (OSError, ValueError, AttributeError):
        return UNREACHABLE
    return OK if (backends.get(backend) or {}).get("up") is True else UNREACHABLE


def whisper_state(url: str, backend: str = "") -> str:
    """Does the check's Whisper answer at all? Any HTTP answer below 500 counts (busy is not dead)."""
    if not url:
        return OFF
    if backend:
        return hub_state(url, backend)
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=TIMEOUT):
            return OK
    except urllib.error.HTTPError as e:
        return OK if e.code < 500 else UNREACHABLE
    except (OSError, ValueError):
        return UNREACHABLE


def push_url(base: str, up: bool, message: str) -> str:
    """The monitor's push address with this beat's status and message (the rest of its query stays)."""
    parts = urllib.parse.urlsplit(base)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query.update({"status": "up" if up else "down", "msg": message})
    query.setdefault("ping", "")
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def verdict(whisper: str) -> tuple[bool, str]:
    if whisper == OK:
        return True, "OK"
    if whisper == OFF:
        return False, "whisper check not configured"
    return False, "whisper check unreachable"


class Heartbeat:
    def __init__(self, whisper_url: str, push_file: Path, engine: str, backend: str = "") -> None:
        self.whisper_url = whisper_url
        self.backend = backend
        self.push_file = push_file
        self.engine = engine
        self.whisper = OFF if not whisper_url else UNREACHABLE

    def beat(self) -> None:
        self.whisper = whisper_state(self.whisper_url, self.backend)
        up, message = verdict(self.whisper)
        try:
            base = self.push_file.read_text(encoding="utf-8").strip()
        except OSError:
            return   # no monitor set up: nothing to push
        try:
            urllib.request.urlopen(push_url(base, up, f"{message} ({self.engine})"), timeout=TIMEOUT).close()
        except (OSError, ValueError) as e:
            _LOGGER.warning("heartbeat not pushed: %s", e)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, self.beat)
            await asyncio.sleep(INTERVAL)
