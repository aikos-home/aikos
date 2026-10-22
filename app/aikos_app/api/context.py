"""What every request handler can reach, and small helpers shared by the route modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import web

from ..auth.service import AuthService
from ..config import Settings
from ..ha.client import HaClient
from ..ha.door import DoorMessages
from ..ha.door_actions import DoorActions
from ..push.door_push import DoorPush
from ..push.ring_push import RingPush
from ..roles import Cap, can
from ..store import Database
from ..store.accounts import Accounts, User
from ..store.audit import Audit
from ..store.push import Pushes
from ..store.sessions import Sessions
from ..talk import TalkBridge
from ..voice import Voices

SESSION_COOKIE = "aikos_session"
NATIVE_CLIENT_HEADER = "X-Aikos-Client"


@dataclass
class AppContext:
    settings: Settings
    db: Database
    accounts: Accounts
    sessions: Sessions
    audit: Audit
    auth: AuthService
    ha: HaClient
    door: DoorMessages
    pushes: Pushes
    door_push: DoorPush
    push_public_key: str
    door_actions: DoorActions
    voices: Voices
    ring_push: RingPush
    talk: TalkBridge


CTX = web.AppKey("aikos_ctx", AppContext)
USER_KEY = "aikos_user"
TOKEN_KEY = "aikos_token"


def ctx(request: web.Request) -> AppContext:
    return request.app[CTX]


def api_error(status: int, code: str) -> web.HTTPException:
    cls = {400: web.HTTPBadRequest, 401: web.HTTPUnauthorized, 403: web.HTTPForbidden, 404: web.HTTPNotFound,
           409: web.HTTPConflict, 429: web.HTTPTooManyRequests, 503: web.HTTPServiceUnavailable}[status]
    return cls(text=f'{{"error": "{code}"}}', content_type="application/json")


def current_user(request: web.Request) -> User:
    user = request.get(USER_KEY)
    if user is None:
        raise api_error(401, "not_signed_in")
    return user


def require(request: web.Request, cap: Cap) -> User:
    user = current_user(request)
    if not can(user.role, cap):
        ctx(request).audit.log("forbidden", False, user.id, target=f"{request.method} {request.path}",
                               ip=client_ip(request))
        raise api_error(403, "forbidden")
    return user


def client_ip(request: web.Request) -> str:
    """Behind the local reverse proxy: X-Real-IP, which the proxy sets from its own trusted-proxy rules (a client cannot
    choose it); else the socket address."""
    if ctx(request).settings.trust_proxy:
        real = request.headers.get("X-Real-IP", "").strip()
        if real:
            return real
    return request.remote or ""


def is_native(request: web.Request) -> bool:
    return request.headers.get(NATIVE_CLIENT_HEADER, "") == "native"


async def json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        raise api_error(400, "bad_json") from None
    if not isinstance(body, dict):
        raise api_error(400, "bad_json")
    return body


def device_label(request: web.Request) -> str:
    """A rough label for the person's passkey and session list ("Android · Chrome"); never an identifier."""
    ua = request.headers.get("User-Agent", "")
    system = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                                  ("Windows", "Windows"), ("Mac OS", "Mac"), ("Linux", "Linux")) if k in ua), "")
    browser = next((n for k, n in (("Edg/", "Edge"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                   ("Safari/", "Safari")) if k in ua), "")
    return " · ".join(p for p in (system, browser) if p)
