"""Meine Stimme (rules A43–A45, S9): a person records, listens to and deletes only their own voice. The recording goes to
the house's voice service and nowhere else; the app keeps no copy."""

from __future__ import annotations

import asyncio

from aiohttp import web

from ..ha.door_actions import QUICK_REPLIES
from ..roles import Cap
from ..voice import VoiceError
from .context import api_error, client_ip, ctx, require

routes = web.RouteTableDef()
_BACKGROUND: set[asyncio.Task] = set()   # kept until done (a task nobody holds may be collected)

AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac")
AUDIO_MAX = 900 * 1024
READING = ("Ich bin einverstanden, dass aikos meine Stimme für Nachrichten an unserer Haustür nachbildet. "
           "Wenn ich nicht da bin, liest die Tür meine Nachrichten mit dieser Stimme vor. Zum Beispiel: "
           "Ich komme sofort, bitte warten Sie einen Moment. Oder: Legen Sie das Paket bitte in die graue Box neben der Tür. "
           "Vielen Dank und einen schönen Tag noch!")
"""Read aloud for the recording: the consent is part of the voice sample itself (S9)."""


def _fail(e: VoiceError) -> web.HTTPException:
    return api_error(e.status if e.status in (400, 404) else 503, e.code)


@routes.get("/api/v1/me/voice")
async def my_voice(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    voices = ctx(request).voices
    voice = None
    if voices.enabled:
        try:
            v = await voices.of(user)
        except VoiceError as e:
            raise _fail(e) from None
        voice = {"seconds": v.get("seconds"), "created": v.get("created")} if v else None
    return web.json_response({"available": voices.enabled, "voice": voice, "reading": READING})


@routes.put("/api/v1/me/voice")
async def enrol(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    if request.content_type not in AUDIO_TYPES:
        raise api_error(400, "bad_type")
    audio = await request.read()
    if not audio or len(audio) > AUDIO_MAX:
        raise api_error(400, "too_large")
    try:
        v = await ctx(request).voices.enrol(user, audio)
    except VoiceError as e:
        raise _fail(e) from None
    c = ctx(request)
    c.audit.log("voice.enrol", True, user.id, ip=client_ip(request))
    task = asyncio.get_running_loop().create_task(c.voices.prepare(user, list(QUICK_REPLIES)))  # play at once afterwards
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return web.json_response({"seconds": v.get("seconds"), "created": v.get("created")})


@routes.delete("/api/v1/me/voice")
async def delete(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    try:
        await ctx(request).voices.delete(user)
    except VoiceError as e:
        raise _fail(e) from None
    ctx(request).audit.log("voice.delete", True, user.id, ip=client_ip(request))
    return web.Response(status=204)


@routes.post("/api/v1/me/voice/sample")
async def sample(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    text = f"Hallo, hier spricht {user.name}. So klinge ich an der Haustür."
    if request.can_read_body and request.content_type == "application/json":   # a sentence of one's own, e.g. an announcement
        try:
            body = await request.json()
        except ValueError:
            raise api_error(400, "bad_request") from None
        own = " ".join(str((body or {}).get("text") or "").split()) if isinstance(body, dict) else ""
        if len(own) > 200:
            raise api_error(400, "bad_request")
        text = own or text
    try:
        wav = await ctx(request).voices.sample(user, text)
    except VoiceError as e:
        raise _fail(e) from None
    return web.Response(body=wav, content_type="audio/wav", headers={"Cache-Control": "private, no-store"})
