"""The aikos app's side: enrol, list and delete a person's voice, and a short test sentence to listen to. Bearer token and a
list of allowed addresses (the app's nodes); the app itself decides who may change whose voice (only the person).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import io
import json
import wave
from collections.abc import Callable
from urllib.parse import unquote

from aiohttp import web

from . import __version__
from .engine import Engine
from .prepare import Preparer
from .voices import UPLOAD_MAX, VoiceError, VoiceStore

_LOGGER = logging.getLogger(__name__)
STORE = web.AppKey("store", VoiceStore)
ENGINE = web.AppKey("engine", Engine)
PREPARER = web.AppKey("preparer", Preparer)
SPEAK_MAX = 300


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


def _error(status: int, code: str) -> web.HTTPException:
    cls = {400: web.HTTPBadRequest, 401: web.HTTPUnauthorized, 403: web.HTTPForbidden, 404: web.HTTPNotFound}[status]
    return cls(text=json.dumps({"error": code}), content_type="application/json")


def create_app(store: VoiceStore, engine: Engine, token: str, allowed: Callable[[str], bool]) -> web.Application:
    @web.middleware
    async def guard(request: web.Request, handler):
        if request.path == "/v1/health":
            return await handler(request)
        if not allowed(request.remote or ""):
            raise _error(403, "address")
        given = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not token or not hmac.compare_digest(given.encode(), token.encode()):
            raise _error(401, "token")
        return await handler(request)

    app = web.Application(middlewares=[guard], client_max_size=UPLOAD_MAX + 1024)
    app[STORE], app[ENGINE] = store, engine
    app[PREPARER] = preparer = Preparer(engine)
    routes = web.RouteTableDef()

    @routes.get("/v1/health")
    async def health(request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "version": __version__, "engine": engine.name, "voices": len(store.all())})

    @routes.get("/v1/voices")
    async def voices(request: web.Request) -> web.Response:
        return web.json_response([v.public for v in store.all()])

    @routes.put("/v1/voices/{voice_id}")
    async def enrol(request: web.Request) -> web.Response:
        name = unquote(request.headers.get("X-Voice-Name", ""))
        audio = await request.read()
        try:
            v = await asyncio.get_running_loop().run_in_executor(None, store.enrol, request.match_info["voice_id"],
                                                                 name, audio)
        except VoiceError as e:
            raise _error(400, str(e)) from None
        return web.json_response(v.public)

    @routes.delete("/v1/voices/{voice_id}")
    async def delete(request: web.Request) -> web.Response:
        try:
            gone = store.delete(request.match_info["voice_id"])
        except VoiceError:
            raise _error(400, "bad voice id") from None
        if not gone:
            raise _error(404, "not_found")
        return web.Response(status=204)

    @routes.post("/v1/prepare")
    async def prepare(request: web.Request) -> web.Response:
        """Say these texts once now, in the background, so they play at once later (quick replies, announcements).
        `draft: true` = text still being typed: made first, and replaces this voice's older draft (prepare.py)."""
        try:
            body = await request.json()
            texts = [" ".join(str(t).split()) for t in body.get("texts") or []][:50]
            voice = str(body.get("voice") or "")
            ref = store.reference(voice)
        except (ValueError, VoiceError, AttributeError):
            raise _error(400, "bad_request") from None
        if ref is None:
            raise _error(404, "voice")
        texts = [t for t in texts if 0 < len(t) <= SPEAK_MAX]
        preparer.add(voice, ref, texts, draft=body.get("draft") is True)
        return web.json_response({"queued": len(texts)}, status=202)

    @routes.post("/v1/speak")
    async def speak(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            raise _error(400, "bad_request") from None
        text = " ".join(str(body.get("text") or "").split())
        try:
            ref = store.reference(str(body.get("voice") or ""))
        except VoiceError:
            ref = None
        if ref is None:
            raise _error(404, "voice")
        if not text or len(text) > SPEAK_MAX:
            raise _error(400, "text")
        try:
            pcm = await asyncio.get_running_loop().run_in_executor(None, engine.synthesize, text, ref)
        except Exception as e:
            _LOGGER.warning("test sentence not spoken: %s", e, exc_info=not isinstance(e, RuntimeError))
            raise web.HTTPBadGateway(text=json.dumps({"error": "speech"}), content_type="application/json") from None
        return web.Response(body=wav_bytes(pcm, engine.rate), content_type="audio/wav",
                            headers={"Cache-Control": "no-store"})

    app.add_routes(routes)
    return app
