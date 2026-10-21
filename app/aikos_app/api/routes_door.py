"""Door: status strip and messages (list, play, heard, forward by hand, delete). Visibility per message follows rule A15,
deleting rule A38, forwarding rule A37 (only when a resident taps "Teilen"; aikos itself never sends sound out)."""

from __future__ import annotations

from dataclasses import asdict

from aiohttp import web

from ..ha.door import DoorMessage, NoRegister, door_status
from ..roles import Cap, may_delete_message, may_see_message
from ..store.accounts import User
from .context import api_error, client_ip, ctx, current_user, require
from .people_view import door_names

routes = web.RouteTableDef()

PASS_HEADERS = ("Content-Length", "Content-Range", "Accept-Ranges")


@routes.get("/api/v1/door/status")
async def status(request: web.Request) -> web.Response:
    current_user(request)
    c = ctx(request)
    return web.json_response(dict(asdict(door_status(c.ha, c.settings)), ha_connected=c.ha.connected))


def _heard(names: list[str], m: DoorMessage) -> bool:
    mine = {n.strip().casefold() for n in names if n}
    return any(b.strip().casefold() in mine for b in m.heard_by)


async def _visible_message(request: web.Request, user: User) -> DoorMessage:
    message = await ctx(request).door.get(request.match_info["message_id"])
    if message is None or not may_see_message(user.role, door_names(user), message.recipient):
        raise api_error(404, "not_found")  # someone else's message does not exist for you (A15)
    return message


@routes.get("/api/v1/door/messages")
async def messages(request: web.Request) -> web.Response:
    user = require(request, Cap.MESSAGES_OWN)
    names = door_names(user)
    visible = [dict(m.public(), heard=_heard(names, m), may_delete=may_delete_message(user.role, names, m.recipient))
               for m in await ctx(request).door.list() if may_see_message(user.role, names, m.recipient)]
    return web.json_response(visible)


@routes.delete("/api/v1/door/messages/{message_id}")
async def delete_message(request: web.Request) -> web.Response:
    user = require(request, Cap.MESSAGES_OWN)
    c = ctx(request)
    message = await _visible_message(request, user)
    if not may_delete_message(user.role, door_names(user), message.recipient):
        c.audit.log("message.delete", False, user.id, target=message.id, ip=client_ip(request))
        raise api_error(403, "forbidden")
    try:
        await c.door.delete(message, user.name)
    except NoRegister:
        raise api_error(503, "no_register") from None
    c.audit.log("message.delete", True, user.id, target=message.id, ip=client_ip(request))
    return web.Response(status=204)


@routes.post("/api/v1/door/messages/{message_id}/heard")
async def heard(request: web.Request) -> web.Response:
    user = require(request, Cap.MESSAGES_OWN)
    message = await _visible_message(request, user)
    try:
        await ctx(request).door.heard(message, user.name)
    except NoRegister:
        raise api_error(503, "no_register") from None
    return web.Response(status=204)


@routes.get("/api/v1/door/messages/{message_id}/audio")
async def message_audio(request: web.Request) -> web.StreamResponse:
    user = require(request, Cap.MESSAGES_OWN)
    c = ctx(request)
    message = await _visible_message(request, user)
    if message.audio_missing:
        raise api_error(404, "not_found")
    share = request.query.get("share") == "1"
    link = await c.door.audio_link(message)
    upstream = await c.ha.media(link, {"Range": request.headers["Range"]} if "Range" in request.headers else None)
    try:
        if upstream.status not in (200, 206):
            raise api_error(503, "ha_error")
        resp = web.StreamResponse(status=upstream.status)
        resp.content_type = message.content_type
        for h in PASS_HEADERS:
            if h in upstream.headers:
                resp.headers[h] = upstream.headers[h]
        resp.headers["Cache-Control"] = "private, no-store"
        if share:  # A37: a resident forwards it by hand; the file name says where it is from
            resp.headers["Content-Disposition"] = f'attachment; filename="aikos-{message.file}"'
        await resp.prepare(request)
        async for chunk in upstream.content.iter_chunked(64 * 1024):
            await resp.write(chunk)
        await resp.write_eof()
    finally:
        upstream.release()
    if share:
        c.audit.log("message.share", True, user.id, target=message.id, ip=client_ip(request))
    elif "Range" not in request.headers or request.headers["Range"].startswith("bytes=0-"):
        c.audit.log("message.play", True, user.id, target=message.id, ip=client_ip(request))
    return resp
