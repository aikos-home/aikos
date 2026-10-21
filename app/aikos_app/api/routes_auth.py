"""Sign-in: first-start setup, invites, login, logout."""

from __future__ import annotations

from aiohttp import web

from ..store.sessions import SESSION_TTL_S
from .context import (SESSION_COOKIE, TOKEN_KEY, client_ip, ctx, current_user, device_label, is_native, json_body)
from .people_view import user_view

routes = web.RouteTableDef()


def signed_in(request: web.Request, user, token: str) -> web.Response:
    """Answer of every successful sign-in: the person, plus the session as cookie (PWA) or in the body (native app)."""
    body = {"user": user_view(user)}
    if is_native(request):
        body["token"] = token
    resp = web.json_response(body)
    if not is_native(request):
        resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_S, httponly=True, secure=True, samesite="Strict",
                        path="/")
    return resp


@routes.get("/api/v1/setup")
async def setup_status(request: web.Request) -> web.Response:
    return web.json_response({"needs_setup": ctx(request).auth.needs_setup()})


@routes.post("/api/v1/setup/start")
async def setup_start(request: web.Request) -> web.Response:
    body = await json_body(request)
    flow, options = ctx(request).auth.setup_start(str(body.get("code", "")), str(body.get("name", "")),
                                                  ip=client_ip(request))
    return web.json_response({"flow": flow, "options": options})


@routes.post("/api/v1/setup/finish")
async def setup_finish(request: web.Request) -> web.Response:
    body = await json_body(request)
    user, token = ctx(request).auth.setup_finish(str(body.get("flow", "")), body.get("credential") or {},
                                                 label=device_label(request), ip=client_ip(request))
    return signed_in(request, user, token)


@routes.post("/api/v1/invites/info")
async def invite_info(request: web.Request) -> web.Response:
    body = await json_body(request)
    invite = ctx(request).auth.invite_info(str(body.get("token", "")))
    return web.json_response({"name": invite.name, "role": invite.role,
                              "kind": "device" if invite.user_id is not None else "new",
                              "expires_at": invite.expires_at})


@routes.post("/api/v1/invites/start")
async def invite_start(request: web.Request) -> web.Response:
    body = await json_body(request)
    flow, options, _ = ctx(request).auth.invite_start(str(body.get("token", "")), ip=client_ip(request))
    return web.json_response({"flow": flow, "options": options})


@routes.post("/api/v1/invites/finish")
async def invite_finish(request: web.Request) -> web.Response:
    body = await json_body(request)
    user, token = ctx(request).auth.invite_finish(str(body.get("flow", "")), body.get("credential") or {},
                                                  label=device_label(request), ip=client_ip(request))
    return signed_in(request, user, token)


@routes.post("/api/v1/login/start")
async def login_start(request: web.Request) -> web.Response:
    flow, options = ctx(request).auth.login_start()
    return web.json_response({"flow": flow, "options": options})


@routes.post("/api/v1/login/finish")
async def login_finish(request: web.Request) -> web.Response:
    body = await json_body(request)
    user, token = ctx(request).auth.login_finish(str(body.get("flow", "")), body.get("credential") or {},
                                                 label=device_label(request), ip=client_ip(request))
    return signed_in(request, user, token)


@routes.post("/api/v1/logout")
async def logout(request: web.Request) -> web.Response:
    current_user(request)
    ctx(request).sessions.revoke(request[TOKEN_KEY])
    resp = web.json_response({"ok": True})
    resp.del_cookie(SESSION_COOKIE, path="/")
    return resp


@routes.post("/api/v1/logout/all")
async def logout_all(request: web.Request) -> web.Response:
    user = current_user(request)
    n = ctx(request).sessions.revoke_all(user.id)
    ctx(request).audit.log("logout.all", True, user.id, target=str(n), ip=client_ip(request))
    resp = web.json_response({"ok": True, "sessions": n})
    resp.del_cookie(SESSION_COOKIE, path="/")
    return resp
