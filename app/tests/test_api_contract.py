"""AT17: every route is described in openapi.json under the versioned prefix; the Android link file is served."""

import json

from conftest import make_settings

from aikos_app.api.routes_meta import OPENAPI
from aikos_app.api.server import create_app


def test_every_route_is_documented(tmp_path):
    app = create_app(make_settings(tmp_path))
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))["paths"]
    for route in app.router.routes():
        info = route.resource.get_info() if route.resource else {}
        path = info.get("path") or info.get("formatter")
        if route.method == "HEAD" or path == "/{tail}":
            continue
        assert path.startswith(("/api/v1/", "/.well-known/")), path
        assert path in spec, path
        assert route.method.lower() in spec[path], (route.method, path)


async def test_assetlinks_default_is_empty(house):
    r = await house.get("/.well-known/assetlinks.json")
    assert r.status == 200 and await r.json() == []


async def test_spa_fallback_and_unknown_api(house):
    web = house.settings.web_dir
    web.mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>aikos</title>", encoding="utf-8")
    r = await house.get("/einladung")
    assert r.status == 200 and "aikos" in await r.text() and r.headers["Cache-Control"] == "no-cache"
    assert (await house.get("/api/v1/nope")).status == 404
    assert (await house.get("/../aikos-app.sqlite3")).status in (200, 404)
    assert "CREATE TABLE" not in await (await house.get("/../data/aikos-app.sqlite3")).text()
