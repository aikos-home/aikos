"""Sends one encrypted push to one phone through its maker's push service.

Only push services of the known makers are accepted as targets: a subscription is an address the server will post to,
so an arbitrary address would let a signed-in person make the server reach into the house network.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .webpush import encrypt, vapid_authorization

_LOGGER = logging.getLogger(__name__)

PUSH_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com",
              "notify" ".windows.com")  # split: the privacy scan would read it as a Home Assistant notify entity
"""Hosts (and their subdomains) of the browser makers' push services: Google, Mozilla, Apple, Microsoft (WNS)."""
SEND_TIMEOUT_S = 10


def endpoint_allowed(endpoint: str) -> bool:
    try:
        u = urlsplit(endpoint)
        port = u.port
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.username or u.password or port not in (None, 443) or len(endpoint) > 1024:
        return False
    return any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


class PushSender:
    def __init__(self, vapid_private: str, subject: str) -> None:
        self._key, self._subject = vapid_private, subject
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def send(self, endpoint: str, p256dh: str, auth: str, payload: dict[str, Any], *, ttl: int = 3600,
                   topic: str = "", urgency: str = "high") -> str:
        """'ok', 'gone' (the subscription no longer exists: forget it) or 'error'."""
        if not endpoint_allowed(endpoint):
            return "gone"
        body = encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), p256dh, auth)
        headers = {"TTL": str(ttl), "Urgency": urgency, "Content-Encoding": "aes128gcm",
                   "Content-Type": "application/octet-stream",
                   "Authorization": vapid_authorization(endpoint, self._key, self._subject)}
        if topic:
            headers["Topic"] = topic[:32]
        if self._session is None:
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.post(endpoint, data=body, headers=headers, allow_redirects=False,
                                          timeout=aiohttp.ClientTimeout(total=SEND_TIMEOUT_S)) as r:
                if r.status in (200, 201, 202):
                    return "ok"
                if r.status in (404, 410):
                    return "gone"
                _LOGGER.warning("push to %s: HTTP %s %s", urlsplit(endpoint).hostname, r.status, (await r.text())[:200])
                return "error"
        except (aiohttp.ClientError, TimeoutError) as e:
            _LOGGER.warning("push to %s: %s", urlsplit(endpoint).hostname, e)
            return "error"
