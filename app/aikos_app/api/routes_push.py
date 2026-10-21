"""Push on this phone: the app's public key, subscribe and unsubscribe this device, a test push to my own devices."""

from __future__ import annotations

from aiohttp import web

from ..push.sender import endpoint_allowed
from ..push.webpush import valid_subscription_keys
from .context import api_error, client_ip, ctx, current_user

routes = web.RouteTableDef()


async def _json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise api_error(400, "bad_request") from None
    if not isinstance(body, dict):
        raise api_error(400, "bad_request")
    return body


@routes.get("/api/v1/push/key")
async def key(request: web.Request) -> web.Response:
    current_user(request)
    return web.json_response({"key": ctx(request).push_public_key})


@routes.post("/api/v1/push/subscription")
async def subscribe(request: web.Request) -> web.Response:
    user = current_user(request)
    body = await _json(request)
    endpoint = str(body.get("endpoint") or "")
    keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    if not endpoint_allowed(endpoint) or not valid_subscription_keys(p256dh, auth):
        ctx(request).audit.log("push.subscribe", False, user.id, target=endpoint[:80], ip=client_ip(request))
        raise api_error(400, "bad_subscription")
    c = ctx(request)
    c.pushes.subscribe(user.id, endpoint, p256dh, auth, str(body.get("label") or "")[:80])
    c.audit.log("push.subscribe", True, user.id, ip=client_ip(request))
    return web.json_response({"ok": True})


@routes.delete("/api/v1/push/subscription")
async def unsubscribe(request: web.Request) -> web.Response:
    user = current_user(request)
    body = await _json(request)
    ctx(request).pushes.unsubscribe(user.id, str(body.get("endpoint") or ""))
    return web.json_response({"ok": True})


@routes.post("/api/v1/push/test")
async def test(request: web.Request) -> web.Response:
    user = current_user(request)
    sent = await ctx(request).door_push.to_user(user.id, {"kind": "test"})
    return web.json_response({"sent": sent})
