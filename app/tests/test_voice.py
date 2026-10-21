"""Meine Stimme (rules A43–A45, S9): each person records, hears and deletes only their own voice; it goes to the house's
voice service only; notes and the greeting are read in the sender's own voice, without one they are only shown."""

from __future__ import annotations

from aiohttp import web
from conftest import ORIGIN, FakeHa, Household
from softauthn import SoftAuthenticator

from aikos_app.api.context import CTX
from aikos_app.voice import Voices, voice_id

TOKEN = "voice-token-for-tests"


def voice_service(seen: list) -> web.Application:
    """A stand-in for the aikos TTS service's HTTP side."""
    voices: dict[str, dict] = {}

    @web.middleware
    async def auth(request, handler):
        seen.append((request.method, request.path, request.headers.get("Authorization"), request.headers.get("X-Voice-Name")))
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            raise web.HTTPUnauthorized()
        return await handler(request)

    app = web.Application(middlewares=[auth])

    async def all_(request):
        return web.json_response(list(voices.values()))

    async def put(request):
        body = await request.read()
        if len(body) < 10:
            raise web.HTTPBadRequest(text='{"error": "too short"}', content_type="application/json")
        v = {"id": request.match_info["id"], "name": request.headers.get("X-Voice-Name", ""), "created": 1, "seconds": 21.5}
        voices[v["id"]] = v
        return web.json_response(v)

    async def delete(request):
        return web.Response(status=204 if voices.pop(request.match_info["id"], None) else 404)

    async def speak(request):
        body = await request.json()
        if body["voice"] not in voices:
            raise web.HTTPNotFound()
        return web.Response(body=b"RIFF....WAVE", content_type="audio/wav")
    app.router.add_get("/v1/voices", all_)
    app.router.add_put("/v1/voices/{id}", put)
    app.router.add_delete("/v1/voices/{id}", delete)
    async def prepare(request):
        body = await request.json()
        seen.append(("PREPARE", body["voice"], tuple(body["texts"]), body.get("draft")))
        return web.json_response({"queued": len(body["texts"])}, status=202)
    app.router.add_post("/v1/speak", speak)
    app.router.add_post("/v1/prepare", prepare)
    return app


async def people(house: Household):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))  # "Alex"
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    _, kim = await house.redeem(await house.invite(admin, "Kim", "child"), SoftAuthenticator(ORIGIN))
    return admin, sam, kim


async def with_service(house: Household, aiohttp_server, seen: list) -> None:
    server = await aiohttp_server(voice_service(seen))
    c = house.client.app[CTX]
    c.voices = Voices(str(server.make_url("")).rstrip("/"), TOKEN)


async def put_voice(house, who, body=b"x" * 2000, ctype="audio/webm"):
    return await house.client.put("/api/v1/me/voice", data=body,
                                  headers={**who.headers, "Origin": ORIGIN, "Content-Type": ctype})


def test_voice_ids_are_stable_per_person_and_say_nothing_about_them():
    from aikos_app.store.accounts import User
    a = User(1, b"A" * 32, "Alex", "superadmin", "", 0, False)
    b = User(2, b"B" * 32, "Alex", "adult", "", 0, False)
    assert voice_id(a) == voice_id(User(9, b"A" * 32, "Anders", "adult", "", 0, False))   # same account handle, same voice
    assert voice_id(a) != voice_id(b) and "alex" not in voice_id(a).lower() and voice_id(a).startswith("v")


async def test_without_a_voice_service_there_is_nothing_to_record(house):
    admin, _, _ = await people(house)
    r = await (await house.get("/api/v1/me/voice", admin)).json()
    assert r["available"] is False and r["voice"] is None and "einverstanden" in r["reading"]
    assert (await put_voice(house, admin)).status == 503


async def test_record_listen_delete_my_own_voice(house, aiohttp_server):
    seen: list = []
    admin, sam, _ = await people(house)
    await with_service(house, aiohttp_server, seen)
    assert (await (await house.get("/api/v1/me/voice", sam)).json())["voice"] is None
    r = await put_voice(house, sam)
    assert r.status == 200 and (await r.json())["seconds"] == 21.5
    put = [s for s in seen if s[0] == "PUT"][0]
    sam_user = house.client.app[CTX].accounts.list_users()[1]
    assert put[1] == f"/v1/voices/{voice_id(sam_user)}" and put[2] == f"Bearer {TOKEN}" and put[3] == "Sam"
    assert (await (await house.get("/api/v1/me/voice", sam)).json())["voice"]["seconds"] == 21.5
    import asyncio
    for _ in range(50):
        if any(s[0] == "PREPARE" for s in seen):
            break
        await asyncio.sleep(0.01)
    assert ("PREPARE", voice_id(sam_user), ("Komme sofort.", "Bitte vor die Tür legen.", "Moment bitte."), False) in seen
    r = await house.post("/api/v1/door/say/draft", {"message": "Ich bin  gleich da"}, who=sam)
    assert r.status == 202
    for _ in range(50):
        if any(s[0] == "PREPARE" and s[3] for s in seen):
            break
        await asyncio.sleep(0.01)
    assert ("PREPARE", voice_id(sam_user), ("Ich bin gleich da",), True) in seen        # typed, made ahead as a draft
    n = len(seen)
    assert (await house.post("/api/v1/door/say/draft", {"message": "Hallo"}, who=admin)).status == 202   # no own voice
    await asyncio.sleep(0.05)
    assert not any(s[0] == "PREPARE" for s in seen[n:])
    assert (await house.post("/api/v1/door/say/draft", {"message": ""}, who=sam)).status == 400
    assert (await (await house.get("/api/v1/me/voice", admin)).json())["voice"] is None   # only Sam's own
    r = await house.post("/api/v1/me/voice/sample", who=sam)
    assert r.status == 200 and r.content_type == "audio/wav"
    assert (await house.post("/api/v1/me/voice/sample", who=admin)).status == 404           # Alex has none
    r = await house.client.delete("/api/v1/me/voice", headers={**sam.headers, "Origin": ORIGIN})
    assert r.status == 204 and (await (await house.get("/api/v1/me/voice", sam)).json())["voice"] is None
    actions = [a["action"] for a in house.client.app[CTX].audit.recent()]
    assert "voice.enrol" in actions and "voice.delete" in actions


async def test_a_bad_recording_and_a_child_are_refused(house, aiohttp_server):
    seen: list = []
    _, sam, kim = await people(house)
    await with_service(house, aiohttp_server, seen)
    r = await put_voice(house, sam, body=b"short")
    assert r.status == 400 and (await r.json())["error"] == "voice_recording"
    assert (await put_voice(house, sam, ctype="text/plain")).status == 400
    assert (await put_voice(house, kim)).status == 403                                       # children: no door actions


async def test_notes_are_read_in_the_senders_own_voice_only(house, fake_ha: FakeHa, aiohttp_server):
    seen: list = []
    fake_ha.use_door_actions()
    admin, sam, _ = await people(house)
    await with_service(house, aiohttp_server, seen)
    await put_voice(house, sam)
    await house.post("/api/v1/door/say", {"message": "Komme sofort"}, who=sam)
    await house.post("/api/v1/door/say", {"message": "Bin gleich da"}, who=admin)
    says = [s for s in fake_ha.services if s[1] == "door_say"]
    sam_user = house.client.app[CTX].accounts.list_users()[1]
    assert says[0][2]["voice"] == voice_id(sam_user) and says[1][2]["voice"] == ""          # Alex: shown only (A45)
    r = await house.client.put("/api/v1/door/greeting", json={"text": "Willkommen!"},
                               headers={**sam.headers, "Origin": ORIGIN})
    assert r.status == 204 and [s for s in fake_ha.services if s[1] == "door_greeting"][-1][2]["voice"] == voice_id(sam_user)


async def test_the_voice_service_being_away_only_means_no_reading_aloud(house, fake_ha: FakeHa):
    fake_ha.use_door_actions()
    _, sam, _ = await people(house)
    house.client.app[CTX].voices = Voices("http://127.0.0.1:9", TOKEN)                       # nobody listens there
    r = await house.post("/api/v1/door/say", {"message": "Komme sofort"}, who=sam)
    assert r.status == 200 and [s for s in fake_ha.services if s[1] == "door_say"][0][2]["voice"] == ""
    assert (await put_voice(house, sam)).status == 503
