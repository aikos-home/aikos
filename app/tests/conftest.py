"""Shared test setup: the app with a fake Home Assistant, a software passkey, and helpers to sign people in."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aikos_app.api.server import SETUP_CODE_FILE, create_app  # noqa: E402
from aikos_app.config import Settings  # noqa: E402
from aikos_app.ha.client import HaClient, HaError  # noqa: E402
from softauthn import SoftAuthenticator  # noqa: E402

ORIGIN = "http://localhost:8780"
SIGNED = "/media/local/door_test/{}?authSig=SIGNATURE-THAT-MUST-NOT-LEAK"


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status, self._body, self.headers = status, body, headers
        self.released = False

        class _Content:
            async def iter_chunked(_self, n):
                for i in range(0, len(body), n):
                    yield body[i:i + n]
        self.content = _Content()

    def release(self) -> None:
        self.released = True


class FakeHa(HaClient):
    """Answers the allowed commands from fixed data; records what was asked."""

    def __init__(self) -> None:
        super().__init__("http://ha.invalid", "token-that-must-not-leak")
        self.files: list[str] = []
        self.history: dict[str, list[dict[str, Any]]] = {}
        self.audio = b"ID3" + b"\x00" * 5000
        self.asked: list[str] = []
        self.states: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    @property
    def connected(self) -> bool:
        return True

    def state(self, entity_id: str):
        return self.states.get(entity_id)

    async def command(self, type_: str, **payload: Any) -> Any:
        self.asked.append(type_)
        if type_ == "media_source/browse_media":
            return {"children": [{"title": f, "media_class": "music", "can_expand": False} for f in self.files]
                    + [{"title": "fotos", "media_class": "directory", "can_expand": True}]}
        if type_ == "history/history_during_period":
            return {e: rows for e, rows in self.history.items() if e in payload["entity_ids"]}
        if type_ == "media_source/resolve_media":
            return {"url": SIGNED.format(payload["media_content_id"].rsplit("/", 1)[1])}
        raise HaError(f"unexpected {type_}")

    async def media(self, url: str, headers: dict[str, str] | None = None):
        rng = (headers or {}).get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            part = self.audio[start:]
            return FakeResponse(206, part, {"Content-Length": str(len(part)), "Accept-Ranges": "bytes",
                                            "Content-Range": f"bytes {start}-{len(self.audio) - 1}/{len(self.audio)}"})
        return FakeResponse(200, self.audio, {"Content-Length": str(len(self.audio)), "Accept-Ranges": "bytes"})


def make_settings(tmp_path: Path, **kw) -> Settings:
    base = dict(public_url=ORIGIN, data_dir=tmp_path / "data", web_dir=tmp_path / "web", door_media_dir="door_test",
                interim_last_message_entity="sensor.aikos_test_last_message",
                interim_message_text_entity="input_text.aikos_test_message_text")
    base.update(kw)
    return Settings(**base)


class Person:
    """A signed-in browser: its session cookie, sent explicitly with each request."""

    def __init__(self, session: str) -> None:
        self.session = session

    @property
    def headers(self) -> dict[str, str]:
        return {"Cookie": f"aikos_session={self.session}"}


def person_of(resp) -> Person | None:
    c = resp.cookies.get("aikos_session")
    return Person(c.value) if c is not None and c.value else None


class Household:
    """Drives the API like the PWA does (Origin header on writes, one cookie per person)."""

    def __init__(self, client, settings: Settings) -> None:
        self.client, self.settings = client, settings

    def setup_code(self) -> str:
        return (self.settings.data_dir / SETUP_CODE_FILE).read_text(encoding="utf-8").strip()

    async def post(self, path: str, body: dict | None = None, who: Person | None = None,
                   headers: dict[str, str] | None = None, origin: str | None = ORIGIN):
        h = dict(who.headers if who else {})
        if origin:
            h["Origin"] = origin
        h.update(headers or {})
        return await self.client.post(path, json=body or {}, headers=h)

    async def get(self, path: str, who: Person | None = None, headers: dict[str, str] | None = None):
        return await self.client.get(path, headers={**(who.headers if who else {}), **(headers or {})})

    async def setup(self, authn: SoftAuthenticator, name: str = "Alex"):
        r = await self.post("/api/v1/setup/start", {"code": self.setup_code(), "name": name})
        assert r.status == 200, await r.text()
        start = await r.json()
        r = await self.post("/api/v1/setup/finish", {"flow": start["flow"], "credential": authn.create(start["options"])})
        return r, person_of(r)

    async def login(self, authn: SoftAuthenticator, key_index: int = -1):
        start = await (await self.post("/api/v1/login/start")).json()
        r = await self.post("/api/v1/login/finish",
                            {"flow": start["flow"], "credential": authn.get(start["options"], key_index)})
        return r, person_of(r)

    async def invite(self, admin: Person, name: str, role: str, ha_person: str = "") -> str:
        r = await self.post("/api/v1/people/invites", {"name": name, "role": role, "ha_person": ha_person}, who=admin)
        assert r.status == 200, await r.text()
        return (await r.json())["link"].split("#", 1)[1]

    async def redeem(self, token: str, authn: SoftAuthenticator):
        start = await (await self.post("/api/v1/invites/start", {"token": token})).json()
        r = await self.post("/api/v1/invites/finish", {"flow": start["flow"], "credential": authn.create(start["options"])})
        return r, person_of(r)


@pytest.fixture
def fake_ha() -> FakeHa:
    return FakeHa()


@pytest.fixture
async def house(tmp_path, fake_ha, aiohttp_client):
    settings = make_settings(tmp_path)
    client = await aiohttp_client(create_app(settings, ha=fake_ha))
    return Household(client, settings)
