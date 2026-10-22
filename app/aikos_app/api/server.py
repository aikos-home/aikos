"""Builds the web application: context, middlewares, API routes, the PWA files, start and stop of the HA connection."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from aiohttp import web

from ..auth.passkeys import Passkeys
from ..auth.service import AuthService
from ..config import Settings
from ..ha.client import HaClient
from ..ha.door import QUIET_SWITCH, REGISTER_ENTITY, DoorMessages
from ..ha.door_actions import ENTITIES as DOOR_ACTION_ENTITIES
from ..ha.door_actions import QUICK_REPLIES
from ..ha.door_actions import DoorActions
from ..ha.door_call import ENTITIES as CALL_ENTITIES
from ..push.door_push import DoorPush
from ..push.ring_push import RingPush
from ..talk import TalkBridge
from ..push.sender import PushSender
from ..push.webpush import new_vapid_key, vapid_public
from ..roles import Cap, can
from ..store import Database
from ..store.accounts import Accounts
from ..store.audit import Audit
from ..store.flows import Flows
from ..store.push import Pushes
from ..store.sessions import Sessions
from ..voice import Voices
from . import (routes_auth, routes_door, routes_door_actions, routes_meta, routes_people, routes_push, routes_talk,
               routes_voice)
from .context import CTX, AppContext, api_error
from .middleware import Brake, brake_middleware, errors, identify, same_origin_writes, security_headers

_LOGGER = logging.getLogger(__name__)
DEFAULT_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SETUP_CODE_FILE = "setup-code.txt"


def build_context(settings: Settings, ha: HaClient | None = None) -> AppContext:
    db = Database.open(settings.db_url, settings.db_user, settings.db_password, settings.db_ca_file,
                       default_file=settings.data_dir / "aikos-app.sqlite3")
    accounts, sessions, audit = Accounts(db), Sessions(db), Audit(db)
    passkeys = Passkeys(settings.rp_id, settings.rp_name, settings.origin)
    auth = AuthService(accounts, sessions, Flows(db), audit, passkeys)
    ha = ha or HaClient(settings.ha_url, settings.ha_token)
    door, pushes = DoorMessages(ha, settings), Pushes(db)
    vapid = pushes.vapid_private(new_vapid_key())
    door_push = DoorPush(ha, door, accounts, pushes, PushSender(vapid, settings.public_url),
                         settings.entity_someone_at_door)
    return AppContext(settings, db, accounts, sessions, audit, auth, ha, door, pushes, door_push, vapid_public(vapid),
                      DoorActions(ha), Voices(settings.tts_url, settings.tts_token),
                      RingPush(ha, accounts, pushes, door_push),
                      TalkBridge(ha, settings.talk_host, settings.talk_port, settings.door_talk_host))


async def prepare_quick_replies(c: AppContext) -> None:
    """After a start: the quick replies in every own voice, made in advance (the voice service keeps them)."""
    if not c.voices.enabled:
        return
    for user in c.accounts.list_users():
        if not user.disabled and can(user.role, Cap.DOOR_ACT) and await c.voices.for_speech(user):
            await c.voices.prepare(user, list(QUICK_REPLIES))


def write_setup_code(c: AppContext) -> Path | None:
    """While nobody exists yet: a fresh one-time code in the data folder (never in the log)."""
    code = c.auth.new_setup_code()
    if code is None:
        return None
    path = c.settings.data_dir / SETUP_CODE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)  # with rqlite nothing else creates the data folder
    path.write_text(code + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _spa(web_dir: Path):
    root = web_dir.resolve()

    async def handler(request: web.Request) -> web.StreamResponse:
        if request.path.startswith("/api/"):
            raise api_error(404, "not_found")
        rel = request.match_info.get("tail", "")
        target = (root / rel).resolve() if rel else root / "index.html"
        if root not in target.parents and target != root / "index.html":
            raise api_error(404, "not_found")
        if not target.is_file():
            target = root / "index.html"
        if not target.is_file():
            return web.Response(text="aikos app: the PWA is not built (app/web: npm run build).", status=503)
        resp = web.FileResponse(target)
        immutable = target.parent.name == "assets"
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return resp

    return handler


def create_app(settings: Settings, ha: HaClient | None = None) -> web.Application:
    c = build_context(settings, ha)
    app = web.Application(client_max_size=1024 * 1024,
                          middlewares=[security_headers, errors, brake_middleware(Brake()), same_origin_writes,
                                       identify])
    app[CTX] = c
    for module in (routes_meta, routes_auth, routes_people, routes_door, routes_door_actions, routes_push, routes_talk,
                   routes_voice):
        app.add_routes(module.routes)
    app.router.add_get("/{tail:.*}", _spa(settings.web_dir or DEFAULT_WEB_DIR))

    background: list[asyncio.Task] = []   # best-effort work after the start (kept so it is not collected)

    async def on_startup(_app: web.Application) -> None:
        if not settings.secure_context:
            _LOGGER.warning("public URL %s is neither HTTPS nor localhost: browsers will refuse passkeys",
                            settings.public_url)
        path = write_setup_code(c)
        if path:
            _LOGGER.warning("nobody is set up yet: the one-time setup code is in %s", path)
        c.ha.watch([settings.entity_someone_at_door, settings.entity_quiet_hours, settings.entity_bell_muted,
                    REGISTER_ENTITY, QUIET_SWITCH, *DOOR_ACTION_ENTITIES, *CALL_ENTITIES])
        c.door_push.attach()
        c.ring_push.attach()
        await c.talk.start()
        await c.ha.start()
        background.append(asyncio.create_task(prepare_quick_replies(c)))

    async def on_cleanup(_app: web.Application) -> None:
        await c.door_push.stop()
        await c.ring_push.stop()
        c.talk.close()
        await c.door_push.sender.close()
        await c.voices.close()
        await c.ha.stop()
        c.db.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app
