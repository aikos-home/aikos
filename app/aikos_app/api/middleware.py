"""Cross-cutting request handling: errors as JSON, security headers, who is asking, same-origin writes, a brake."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from aiohttp import web

from ..auth.service import AuthError
from ..ha.client import HaError, HaNotConnected
from .context import SESSION_COOKIE, TOKEN_KEY, USER_KEY, api_error, client_ip, ctx, is_native

_LOGGER = logging.getLogger(__name__)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'; object-src 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}
AUTH_ERROR_STATUS = {"forbidden": 403, "already_set_up": 409}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
BRAKE_PREFIXES = ("/api/v1/setup", "/api/v1/login", "/api/v1/invites")
BRAKE_LIMIT, BRAKE_WINDOW_S = 30, 600


@web.middleware
async def errors(request: web.Request, handler):
    try:
        return await handler(request)
    except AuthError as e:
        raise api_error(AUTH_ERROR_STATUS.get(e.code, 400), e.code) from None
    except HaNotConnected:
        raise api_error(503, "ha_unreachable") from None
    except HaError as e:
        _LOGGER.warning("Home Assistant: %s", e)
        raise api_error(503, "ha_error") from None


@web.middleware
async def security_headers(request: web.Request, handler):
    try:
        resp = await handler(request)
    except web.HTTPException as e:
        e.headers.update(SECURITY_HEADERS)
        raise
    resp.headers.update(SECURITY_HEADERS)
    if request.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@web.middleware
async def identify(request: web.Request, handler):
    """Bearer token (native app) or session cookie (PWA) → the signed-in person, if any."""
    c = ctx(request)
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else request.cookies.get(SESSION_COOKIE, "")
    if token:
        session = c.sessions.resolve(token)
        user = c.accounts.get_user(session.user_id) if session else None
        if user and not user.disabled:
            request[USER_KEY] = user
            request[TOKEN_KEY] = token
    return await handler(request)


@web.middleware
async def same_origin_writes(request: web.Request, handler):
    """Writes from a browser must come from the app's own origin (with SameSite=Strict cookies: no cross-site writes)."""
    if request.method in WRITE_METHODS and request.path.startswith("/api/"):
        bearer = request.headers.get("Authorization", "").startswith("Bearer ")
        if not (bearer or is_native(request)):
            if request.headers.get("Origin", "") != ctx(request).settings.origin:
                raise api_error(403, "bad_origin")
    return await handler(request)


class Brake:
    """At most BRAKE_LIMIT sign-in attempts per address in BRAKE_WINDOW_S."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        t = time.monotonic()
        hits = self._hits[key]
        while hits and t - hits[0] > BRAKE_WINDOW_S:
            hits.popleft()
        if len(hits) >= BRAKE_LIMIT:
            return False
        hits.append(t)
        return True


def brake_middleware(brake: Brake):
    @web.middleware
    async def brake_mw(request: web.Request, handler):
        if request.method == "POST" and request.path.startswith(BRAKE_PREFIXES):
            if not brake.allow(client_ip(request)):
                raise api_error(429, "slow_down")
        return await handler(request)
    return brake_mw
