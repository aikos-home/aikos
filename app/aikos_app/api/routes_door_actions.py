"""Door actions (rules A11–A14, A39–A41): bell mute and quiet hours (`bell.settings`); a note to the door, the door picture
and the greeting (`door.act`). Every write names the acting person for Home Assistant and goes into the audit log."""

from __future__ import annotations

import re

from aiohttp import web

from ..ha.door_actions import NoDoorActions, actions_state
from ..roles import Cap
from .context import api_error, client_ip, ctx, current_user, require

routes = web.RouteTableDef()

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PICTURE_TYPES = ("image/jpeg", "image/png", "image/webp")
AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac")
PICTURE_MAX = 900 * 1024        # the phone shrinks the photo first; the whole request stays under the app's 1 MB
AUDIO_MAX = 900 * 1024


async def _json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise api_error(400, "bad_request") from None
    if not isinstance(body, dict):
        raise api_error(400, "bad_request")
    return body


async def _raw(request: web.Request, types: tuple[str, ...], limit: int) -> bytes:
    if request.content_type not in types:
        raise api_error(400, "bad_type")
    data = await request.read()
    if not data or len(data) > limit:
        raise api_error(400, "too_large")
    return data


def _audit(request: web.Request, action: str, user_id: int, target: str = "") -> None:
    ctx(request).audit.log(action, True, user_id, target=target, ip=client_ip(request))


async def _do(coro):
    try:
        return await coro
    except NoDoorActions:
        raise api_error(503, "no_door_actions") from None


@routes.get("/api/v1/door/actions")
async def state(request: web.Request) -> web.Response:
    current_user(request)
    return web.json_response(actions_state(ctx(request).ha))


# bell mute and quiet hours
@routes.post("/api/v1/door/bell")
async def bell(request: web.Request) -> web.Response:
    user = require(request, Cap.BELL_SETTINGS)
    body = await _json(request)
    door = ctx(request).door_actions
    if body.get("off"):
        await _do(door.unmute())
        _audit(request, "bell.unmute", user.id)
    else:
        minutes = body.get("minutes")
        until = str(body.get("until_time") or "")
        if body.get("forever") is True:
            await _do(door.mute(forever=True))
        elif isinstance(minutes, int) and not isinstance(minutes, bool) and 1 <= minutes <= 7 * 24 * 60:
            await _do(door.mute(minutes=minutes))
        elif _TIME.match(until):
            await _do(door.mute(until_time=until))
        else:
            raise api_error(400, "bad_request")
        _audit(request, "bell.mute", user.id, target=str(minutes or until or "forever"))
    return web.Response(status=204)


@routes.post("/api/v1/door/quiet-hours")
async def quiet_hours(request: web.Request) -> web.Response:
    user = require(request, Cap.BELL_SETTINGS)
    body = await _json(request)
    data: dict = {}
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise api_error(400, "bad_request")
        data["enabled"] = body["enabled"]
    for key in ("start", "end"):
        if key in body:
            if not _TIME.match(str(body[key])):
                raise api_error(400, "bad_request")
            data[key] = body[key]
    if not data:
        raise api_error(400, "bad_request")
    await _do(ctx(request).door_actions.quiet_hours(data))
    _audit(request, "quiet_hours.set", user.id, target=",".join(f"{k}={v}" for k, v in data.items()))
    return web.Response(status=204)


# a note to the door
@routes.post("/api/v1/door/say")
async def say(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    message = " ".join(str((await _json(request)).get("message") or "").split())
    if not message or len(message) > 400:
        raise api_error(400, "bad_request")
    delivered = await _do(ctx(request).door_actions.say(message, user.name))
    _audit(request, "door.say", user.id, target=delivered)
    return web.json_response({"delivered": delivered})


@routes.delete("/api/v1/door/say")
async def cancel_say(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    await _do(ctx(request).door_actions.cancel_note())
    _audit(request, "door.say_cancel", user.id)
    return web.Response(status=204)


# the door picture
@routes.put("/api/v1/door/picture")
async def put_picture(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    data = await _raw(request, PICTURE_TYPES, PICTURE_MAX)
    await _do(ctx(request).door_actions.set_picture(data))
    _audit(request, "door.picture", user.id)
    return web.Response(status=204)


@routes.delete("/api/v1/door/picture")
async def delete_picture(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    await _do(ctx(request).door_actions.clear_picture())
    _audit(request, "door.picture_clear", user.id)
    return web.Response(status=204)


async def _stream(request: web.Request, link: str, content_type: str) -> web.StreamResponse:
    if not link:
        raise api_error(404, "not_found")
    upstream = await ctx(request).ha.media(link)
    try:
        if upstream.status != 200:
            raise api_error(404, "not_found")
        resp = web.StreamResponse()
        resp.content_type = upstream.headers.get("Content-Type", content_type).split(";")[0] or content_type
        resp.headers["Cache-Control"] = "private, no-store"
        await resp.prepare(request)
        async for chunk in upstream.content.iter_chunked(64 * 1024):
            await resp.write(chunk)
        await resp.write_eof()
        return resp
    finally:
        upstream.release()


@routes.get("/api/v1/door/picture")
async def get_picture(request: web.Request) -> web.StreamResponse:
    require(request, Cap.DOOR_ACT)
    return await _stream(request, ctx(request).door_actions.picture_path(), "image/png")


# the greeting
@routes.put("/api/v1/door/greeting")
async def put_greeting(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    body = await _json(request)
    data: dict = {}
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise api_error(400, "bad_request")
        data["enabled"] = body["enabled"]
    if "text" in body:
        text = " ".join(str(body["text"] or "").split())
        if len(text) > 120:
            raise api_error(400, "bad_request")
        data["text"] = text
    if body.get("always") is True:
        data["clear_window"] = True
    for key in ("start", "end"):
        if body.get(key):
            data[key] = str(body[key])[:40]
    await _do(ctx(request).door_actions.set_greeting(data))
    _audit(request, "door.greeting", user.id)
    return web.Response(status=204)


@routes.put("/api/v1/door/greeting/audio")
async def put_greeting_audio(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    data = await _raw(request, AUDIO_TYPES, AUDIO_MAX)
    await _do(ctx(request).door_actions.set_greeting_audio(data))
    _audit(request, "door.greeting_audio", user.id)
    return web.Response(status=204)


@routes.delete("/api/v1/door/greeting/audio")
async def delete_greeting_audio(request: web.Request) -> web.Response:
    user = require(request, Cap.DOOR_ACT)
    await _do(ctx(request).door_actions.clear_greeting_audio())
    _audit(request, "door.greeting_audio_clear", user.id)
    return web.Response(status=204)


@routes.get("/api/v1/door/greeting/audio")
async def get_greeting_audio(request: web.Request) -> web.StreamResponse:
    require(request, Cap.DOOR_ACT)
    link = await _do(ctx(request).door_actions.greeting_audio_link())
    return await _stream(request, link, "audio/webm")
