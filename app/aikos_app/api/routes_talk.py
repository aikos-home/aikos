"""The live call at the door (A47, A48): what is said there, live (`GET /api/v1/door/call`), and talking to the door while
a button is held (`GET /api/v1/door/talk`, a WebSocket). Both `door.act`; talking only from the app's own origin."""

from __future__ import annotations

import asyncio
import json

from aiohttp import WSMsgType, web

from ..ha.door_call import call_state
from ..roles import Cap
from ..talk import TalkSession
from .context import api_error, client_ip, ctx, require

routes = web.RouteTableDef()
FRAME_MAX = 64 * 1024


@routes.get("/api/v1/door/call")
async def call(request: web.Request) -> web.Response:
    require(request, Cap.DOOR_ACT)
    c = ctx(request)
    return web.json_response({**call_state(c.ha), "talk": c.talk.enabled})


@routes.get("/api/v1/door/talk")
async def talk(request: web.Request) -> web.StreamResponse:
    """Phone → server: binary = 16-bit LE PCM, 16 kHz mono (sent only while held); text = {"hold": true|false}.
    Server → phone: binary = the door's microphone, same format; text = {"state": "listening"|"talking"|"busy"|"off"}."""
    user = require(request, Cap.DOOR_ACT)
    c = ctx(request)
    if request.headers.get("Origin", "") != c.settings.origin:
        raise api_error(403, "bad_origin")   # a WebSocket is not covered by the write check
    if not c.talk.enabled:
        raise api_error(503, "no_talk")
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=FRAME_MAX)
    await ws.prepare(request)
    if c.talk.session is not None:
        await ws.send_json({"state": "busy"})
        await ws.close()
        return ws
    session = TalkSession(c.talk, ws.send_bytes, name=user.name)
    c.audit.log("door.talk", True, user.id, target="start", ip=client_ip(request))
    try:
        await session.open()
        await ws.send_json({"state": "listening"})
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                session.from_phone(msg.data)
            elif msg.type == WSMsgType.TEXT:
                try:
                    hold = json.loads(msg.data).get("hold")
                except (ValueError, AttributeError):
                    continue
                if isinstance(hold, bool):
                    await session.hold(hold)
                    await ws.send_json({"state": "talking" if hold else "listening"})
    finally:
        async def leave() -> None:
            await session.close()
            c.audit.log("door.talk", True, user.id, target="end", ip=client_ip(request))
        # the phone going away cancels this handler: leaving the door must still happen (else the door keeps a dead key)
        await asyncio.shield(leave())
    return ws
