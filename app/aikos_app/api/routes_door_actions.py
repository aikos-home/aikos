"""Door actions (rules A11–A14, A39–A41): bell mute and quiet hours (`bell.settings`); a note to the door, the door picture,
the greeting and the door announcements (`door.act`; sprachausgabe S10–S14). Every write names the acting person for Home
Assistant and goes into the audit log."""

from __future__ import annotations

import asyncio
import re

from aiohttp import web

from ..ha.door_actions import SITUATIONS, NoDoorActions, actions_state
from ..roles import Cap
from .context import api_error, client_ip, ctx, current_user, require

routes = web.RouteTableDef()

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_ZONE = re.compile(r"^zone\.[a-z0-9_]+$")
SENTENCE_MAX, PLACE_MAX, PLACES_MAX = 200, 40, 20
_DRAFTS: set[asyncio.Task] = set()   # kept until done (a task nobody holds may be collected)
PICTURE_TYPES = ("image/jpeg", "image/png", "image/webp")
AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac")
PICTURE_MAX = 900 * 1024        # the phone shrinks the photo first; the whole request stays under the app's 1 MB
AUDIO_MAX = 900 * 1024
VOICE_MAX_S = 50                 # the door plays at most 50 s of a sound


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
    user = current_user(request)
    return web.json_response(actions_state(ctx(request).ha, user.ha_person))


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
    c = ctx(request)
    delivered = await _do(c.door_actions.say(message, user.name, await c.voices.for_speech(user)))
    _audit(request, "door.say", user.id, target=delivered)
    return web.json_response({"delivered": delivered})


@routes.post("/api/v1/door/say/draft")
async def say_draft(request: web.Request) -> web.Response:
    """The note still being typed: its speech is made now, so it plays at once when it is sent (only with an own voice;
    nothing reaches the door)."""
    user = require(request, Cap.DOOR_ACT)
    message = " ".join(str((await _json(request)).get("message") or "").split())
    if not message or len(message) > 400:
        raise api_error(400, "bad_request")
    c = ctx(request)
    if await c.voices.for_speech(user):
        task = asyncio.get_running_loop().create_task(c.voices.prepare(user, [message], draft=True))
        _DRAFTS.add(task)
        task.add_done_callback(_DRAFTS.discard)
    return web.Response(status=202)


@routes.post("/api/v1/door/say/audio")
async def say_audio(request: web.Request) -> web.Response:
    """A voice message to the door (A49, "wie bei WhatsApp"): the recording itself, in the sender's own voice; `seconds`
    in the query (for the chat)."""
    user = require(request, Cap.DOOR_ACT)
    try:
        seconds = round(min(max(float(request.query.get("seconds") or 0), 0), VOICE_MAX_S), 1)
    except ValueError:
        raise api_error(400, "bad_request") from None
    data = await _raw(request, AUDIO_TYPES, AUDIO_MAX)
    delivered = await _do(ctx(request).door_actions.say_audio(data, user.name, seconds))
    _audit(request, "door.say_audio", user.id, target=delivered)
    return web.json_response({"delivered": delivered})


@routes.get("/api/v1/door/voice/{name}")
async def get_voice(request: web.Request) -> web.StreamResponse:
    """A voice message of the chat, to listen to it again."""
    require(request, Cap.DOOR_ACT)
    link = await _do(ctx(request).door_actions.voice_link(request.match_info["name"]))
    return await _stream(request, link, "audio/webm")


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
    if "text" in data:  # the greeting text is read in the voice of whoever saved it (A45)
        data["voice"] = await ctx(request).voices.for_speech(user)
    await _do(ctx(request).door_actions.set_greeting(data))
    _audit(request, "door.greeting", user.id)
    return web.Response(status=204)


# the door announcements
def _sentence(value: object) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > SENTENCE_MAX:
        raise api_error(400, "bad_request")
    return text


@routes.put("/api/v1/door/announcements")
async def put_announcements(request: web.Request) -> web.Response:
    """Sentences, level, places; `name_me` = the caller agrees (or no longer) that the door names their own place. Nobody
    can agree for another person."""
    user = require(request, Cap.DOOR_ACT)
    body = await _json(request)
    c = ctx(request)
    data: dict = {}
    if "disclosure" in body:
        level = body["disclosure"]
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 4:
            raise api_error(400, "bad_request")
        data["disclosure"] = level
    for key in (*SITUATIONS, "away_places"):
        if key in body:
            data[key] = _sentence(body[key])
    if "places" in body:
        places = body["places"]
        if not isinstance(places, dict) or len(places) > PLACES_MAX:
            raise api_error(400, "bad_request")
        data["places"] = {}
        for zone, phrase in places.items():
            text = " ".join(str(phrase or "").split())
            if not _ZONE.match(str(zone)) or len(text) > PLACE_MAX:
                raise api_error(400, "bad_request")
            data["places"][zone] = text
    if "name_me" in body:
        if not isinstance(body["name_me"], bool) or not user.ha_person:
            raise api_error(400, "bad_request")
        named = [p for p in c.door_actions.named() if p != user.ha_person]
        data["named"] = named + [user.ha_person] if body["name_me"] else named
    if any(k in data for k in (*SITUATIONS, "away_places")):   # the sentences are said in the voice of whoever saved them
        data["voice"] = await c.voices.for_speech(user)
    if not data:
        raise api_error(400, "bad_request")
    await _do(c.door_actions.set_announcements(data))
    _audit(request, "door.announcements", user.id, target=",".join(sorted(data)))
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
