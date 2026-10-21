"""Builds the web application: context, middlewares, API routes, the PWA files, start and stop of the HA connection."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from aiohttp import web

from ..auth.passkeys import Passkeys
from ..auth.service import AuthService
from ..config import Settings
from ..ha.client import HaClient
from ..ha.door import DoorMessages
from ..store import Database
from ..store.accounts import Accounts
from ..store.audit import Audit
from ..store.flows import Flows
from ..store.sessions import Sessions
from . import routes_auth, routes_door, routes_meta, routes_people
from .context import CTX, AppContext, api_error
from .middleware import Brake, brake_middleware, errors, identify, same_origin_writes, security_headers

_LOGGER = logging.getLogger(__name__)
DEFAULT_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SETUP_CODE_FILE = "setup-code.txt"


def build_context(settings: Settings, ha: HaClient | None = None) -> AppContext:
    db = Database(settings.data_dir / "aikos-app.sqlite3")
    accounts, sessions, audit = Accounts(db), Sessions(db), Audit(db)
    passkeys = Passkeys(settings.rp_id, settings.rp_name, settings.origin)
    auth = AuthService(accounts, sessions, Flows(db), audit, passkeys)
    ha = ha or HaClient(settings.ha_url, settings.ha_token)
    return AppContext(settings, db, accounts, sessions, audit, auth, ha, DoorMessages(ha, settings))


def write_setup_code(c: AppContext) -> Path | None:
    """While nobody exists yet: a fresh one-time code in the data folder (never in the log)."""
    code = c.auth.new_setup_code()
    if code is None:
        return None
    path = c.settings.data_dir / SETUP_CODE_FILE
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
    for module in (routes_meta, routes_auth, routes_people, routes_door):
        app.add_routes(module.routes)
    app.router.add_get("/{tail:.*}", _spa(settings.web_dir or DEFAULT_WEB_DIR))

    async def on_startup(_app: web.Application) -> None:
        if not settings.secure_context:
            _LOGGER.warning("public URL %s is neither HTTPS nor localhost: browsers will refuse passkeys",
                            settings.public_url)
        path = write_setup_code(c)
        if path:
            _LOGGER.warning("nobody is set up yet: the one-time setup code is in %s", path)
        c.ha.watch([settings.entity_someone_at_door, settings.entity_quiet_hours, settings.entity_bell_muted])
        await c.ha.start()

    async def on_cleanup(_app: web.Application) -> None:
        await c.ha.stop()
        c.db.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app
