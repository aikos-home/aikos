"""Door: status strip and messages (list, play). Visibility per message follows rule A15."""

from __future__ import annotations

from dataclasses import asdict

from aiohttp import web

from ..ha.door import door_status
from ..roles import Cap, may_see_message
from .context import api_error, client_ip, ctx, current_user, require
from .people_view import door_names

routes = web.RouteTableDef()

PASS_HEADERS = ("Content-Length", "Content-Range", "Accept-Ranges")


@routes.get("/api/v1/door/status")
async def status(request: web.Request) -> web.Response:
    current_user(request)
    c = ctx(request)
    return web.json_response(dict(asdict(door_status(c.ha, c.settings)), ha_connected=c.ha.connected))


@routes.get("/api/v1/door/messages")
async def messages(request: web.Request) -> web.Response:
    user = require(request, Cap.MESSAGES_OWN)
    names = door_names(user)
    visible = [m.public() for m in await ctx(request).door.list() if may_see_message(user.role, names, m.recipient)]
    return web.json_response(visible)


@routes.get("/api/v1/door/messages/{message_id}/audio")
async def message_audio(request: web.Request) -> web.StreamResponse:
    user = require(request, Cap.MESSAGES_OWN)
    c = ctx(request)
    message = await c.door.get(request.match_info["message_id"])
    if message is None or not may_see_message(user.role, door_names(user), message.recipient):
        raise api_error(404, "not_found")  # someone else's message does not exist for you (A15)
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
        await resp.prepare(request)
        async for chunk in upstream.content.iter_chunked(64 * 1024):
            await resp.write(chunk)
        await resp.write_eof()
    finally:
        upstream.release()
    if "Range" not in request.headers or request.headers["Range"].startswith("bytes=0-"):
        c.audit.log("message.play", True, user.id, target=message.id, ip=client_ip(request))
    return resp
