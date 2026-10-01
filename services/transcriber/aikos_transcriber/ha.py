"""Home Assistant REST calls.

Part of the aikos transcriber (split from roomkey tools/transcribe_publish.py at d0d52b9, code unchanged)."""
from __future__ import annotations

import json
import urllib.request


def ha(url: str, token: str, method: str, path: str, body=None):
    req = urllib.request.Request(url.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def key_for_ip(url: str, token: str, ip: str):
    """Find which key sent the audio: the *_ip_address sensor whose state is that IP."""
    for s in ha(url, token, "GET", "/api/states"):
        if s["entity_id"].endswith("_ip_address") and s["state"] == ip:
            name = s["attributes"].get("friendly_name", "").removesuffix(" IP address").strip()
            return name, s["entity_id"].split(".", 1)[1].removesuffix("_ip_address")
    return None, None
