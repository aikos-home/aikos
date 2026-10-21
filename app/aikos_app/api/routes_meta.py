"""Health, the API description, and the Android app link file."""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web

from .. import __version__
from .context import ctx

routes = web.RouteTableDef()
OPENAPI = Path(__file__).with_name("openapi.json")


@routes.get("/api/v1/health")
async def health(request: web.Request) -> web.Response:
    """Ready = the service runs and reaches its database. Home Assistant being away does not make a node unhealthy
    (all three would drop out together); it is reported separately."""
    c = ctx(request)
    db_ok = c.db.ping()
    body = {"ok": db_ok, "version": __version__, "commit": c.settings.commit, "db": db_ok, "ha_connected": c.ha.connected}
    return web.json_response(body, status=200 if db_ok else 503)


@routes.get("/api/v1/openapi.json")
async def openapi(request: web.Request) -> web.Response:
    return web.json_response(json.loads(OPENAPI.read_text(encoding="utf-8")))


@routes.get("/.well-known/assetlinks.json")
async def assetlinks(request: web.Request) -> web.Response:
    """For a later Android app sharing the passkeys of this domain (A17). Empty until there is one."""
    path = ctx(request).settings.assetlinks_file
    data = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else []
    return web.json_response(data)
