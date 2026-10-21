"""The signed-in person (profile, passkeys) and, for the superadmin, the household's people and invites."""

from __future__ import annotations

from aiohttp import web

from ..roles import Cap
from .context import api_error, client_ip, ctx, current_user, device_label, json_body, require
from .people_view import credential_id, credential_view, user_view

routes = web.RouteTableDef()


def invite_link(request: web.Request, token: str) -> str:
    # The token sits in the fragment: browsers never send it to a server, proxy logs stay clean.
    return f"{ctx(request).settings.public_url}/einladung#{token}"


@routes.get("/api/v1/me")
async def me(request: web.Request) -> web.Response:
    return web.json_response(user_view(current_user(request)))


@routes.get("/api/v1/me/passkeys")
async def my_passkeys(request: web.Request) -> web.Response:
    user = current_user(request)
    return web.json_response([credential_view(c) for c in ctx(request).accounts.credentials_of(user.id)])


@routes.post("/api/v1/me/passkeys/start")
async def add_passkey_start(request: web.Request) -> web.Response:
    flow, options = ctx(request).auth.add_passkey_start(current_user(request))
    return web.json_response({"flow": flow, "options": options})


@routes.post("/api/v1/me/passkeys/finish")
async def add_passkey_finish(request: web.Request) -> web.Response:
    body = await json_body(request)
    ctx(request).auth.add_passkey_finish(current_user(request), str(body.get("flow", "")), body.get("credential") or {},
                                         label=device_label(request))
    return web.json_response({"ok": True})


@routes.delete("/api/v1/me/passkeys/{cred_id}")
async def delete_passkey(request: web.Request) -> web.Response:
    user = current_user(request)
    cred = credential_id(request.match_info["cred_id"])
    if cred is None or not ctx(request).accounts.delete_credential(user.id, cred):
        raise api_error(409, "last_passkey_or_unknown")
    ctx(request).audit.log("passkey.delete", True, user.id, ip=client_ip(request))
    return web.json_response({"ok": True})


@routes.get("/api/v1/people")
async def people(request: web.Request) -> web.Response:
    require(request, Cap.PEOPLE_MANAGE)
    return web.json_response([dict(user_view(u), disabled=u.disabled) for u in ctx(request).accounts.list_users()])


@routes.post("/api/v1/people/invites")
async def create_invite(request: web.Request) -> web.Response:
    actor = require(request, Cap.PEOPLE_MANAGE)
    body = await json_body(request)
    token, invite = ctx(request).auth.create_invite(actor, str(body.get("name", "")), str(body.get("role", "")),
                                                    str(body.get("ha_person", "")))
    return web.json_response({"link": invite_link(request, token), "expires_at": invite.expires_at})


@routes.post("/api/v1/people/{user_id:\\d+}/device-invite")
async def device_invite(request: web.Request) -> web.Response:
    actor = require(request, Cap.PEOPLE_MANAGE)
    token, invite = ctx(request).auth.device_invite(int(request.match_info["user_id"]), created_by=actor.id)
    return web.json_response({"link": invite_link(request, token), "expires_at": invite.expires_at})


@routes.post("/api/v1/people/{user_id:\\d+}/disable")
async def disable_person(request: web.Request) -> web.Response:
    actor = require(request, Cap.PEOPLE_MANAGE)
    user_id = int(request.match_info["user_id"])
    if user_id == actor.id:
        raise api_error(409, "cannot_disable_self")
    ctx(request).accounts.disable_user(user_id)
    ctx(request).audit.log("people.disable", True, actor.id, target=str(user_id), ip=client_ip(request))
    return web.json_response({"ok": True})
