"""Door actions through the app (rules A11–A14, A39–A41, matrix 2.4a): who may mute the bell, set quiet hours, send a note,
put a picture or a greeting on the door; each is exactly one aikos service with the acting person, recorded in the audit log."""

from __future__ import annotations

from conftest import ORIGIN, FakeHa, Household
from softauthn import SoftAuthenticator

from aikos_app.api.context import CTX


async def people(house: Household):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))  # "Alex", superadmin
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    _, kim = await house.redeem(await house.invite(admin, "Kim", "child"), SoftAuthenticator(ORIGIN))
    return admin, sam, kim


def door(ha: FakeHa) -> None:
    ha.use_door_actions()  # someone at the door, for the double: binary_sensor.aikos_test_someone


def actions(ha: FakeHa) -> list:
    return [s for s in ha.services if s[1] != "door_messages"]


async def put(house: Household, path: str, body: bytes, content_type: str, who):
    return await house.client.put(path, data=body, headers={**who.headers, "Origin": ORIGIN, "Content-Type": content_type})


async def audit_actions(house: Household) -> list[str]:
    return [a["action"] for a in house.client.app[CTX].audit.recent()]


async def test_bell_mute_choices(house, fake_ha):
    door(fake_ha)
    admin, sam, _ = await people(house)
    for body in ({"minutes": 60}, {"until_time": "07:00"}, {"forever": True}, {"off": True}):
        assert (await house.post("/api/v1/door/bell", body, who=sam)).status == 204, body
    assert actions(fake_ha) == [("aikos", "bell_mute", {"minutes": 60}), ("aikos", "bell_mute", {"until_time": "07:00"}),
                                ("aikos", "bell_mute", {"forever": True}), ("aikos", "bell_unmute", {})]
    for bad in ({}, {"minutes": 0}, {"minutes": True}, {"minutes": 99999}, {"until_time": "7 Uhr"}, {"forever": "yes"}):
        assert (await house.post("/api/v1/door/bell", bad, who=admin)).status == 400, bad
    assert (await audit_actions(house)).count("bell.mute") == 3


async def test_quiet_hours(house, fake_ha):
    door(fake_ha)
    admin, _, _ = await people(house)
    r = await house.post("/api/v1/door/quiet-hours", {"enabled": True, "start": "21:30", "end": "06:45"}, who=admin)
    assert r.status == 204
    assert actions(fake_ha) == [("aikos", "quiet_hours", {"enabled": True, "start": "21:30", "end": "06:45"})]
    for bad in ({}, {"start": "25:00"}, {"enabled": "on"}):
        assert (await house.post("/api/v1/door/quiet-hours", bad, who=admin)).status == 400


async def test_a_child_may_do_none_of_it(house, fake_ha):
    """Matrix 2.4a: children get no door actions and no bell settings."""
    door(fake_ha)
    _, _, kim = await people(house)
    for path, body in (("/api/v1/door/bell", {"minutes": 60}), ("/api/v1/door/quiet-hours", {"enabled": False}),
                       ("/api/v1/door/say", {"message": "Hallo"})):
        assert (await house.post(path, body, who=kim)).status == 403, path
    assert (await put(house, "/api/v1/door/picture", b"x", "image/jpeg", kim)).status == 403
    assert actions(fake_ha) == []


async def test_a_note_now_or_for_the_next_visitor(house, fake_ha):
    door(fake_ha)
    _, sam, _ = await people(house)
    r = await house.post("/api/v1/door/say", {"message": "  Paket bitte\nin die Box "}, who=sam)
    assert (await r.json()) == {"delivered": "waiting"}
    assert actions(fake_ha)[-1] == ("aikos", "door_say", {"message": "Paket bitte in die Box", "sender": "Sam", "voice": ""})
    state = await (await house.get("/api/v1/door/actions", sam)).json()
    assert state["note"]["message"] == "Paket bitte in die Box" and state["note"]["sender"] == "Sam"
    fake_ha.states["binary_sensor.aikos_test_someone"] = {"state": "on"}
    assert (await (await house.post("/api/v1/door/say", {"message": "Komme sofort"}, who=sam)).json())["delivered"] == "now"
    assert (await house.client.delete("/api/v1/door/say", headers={**sam.headers, "Origin": ORIGIN})).status == 204
    assert actions(fake_ha)[-1][1] == "door_say_cancel"
    for bad in ({}, {"message": "   "}, {"message": "x" * 401}):
        assert (await house.post("/api/v1/door/say", bad, who=sam)).status == 400


async def test_picture_upload_and_preview(house, fake_ha):
    door(fake_ha)
    admin, _, _ = await people(house)
    assert (await house.get("/api/v1/door/picture", admin)).status == 404           # none yet
    r = await put(house, "/api/v1/door/picture", b"JPEGDATA", "image/jpeg", admin)
    assert r.status == 204
    name, service, data = actions(fake_ha)[-1]
    assert service == "door_picture" and data["image"] == "SlBFR0RBVEE="                  # base64 of the body
    r = await house.get("/api/v1/door/picture", admin)
    assert r.status == 200 and r.content_type == "image/png" and await r.read() == fake_ha.picture
    assert (await put(house, "/api/v1/door/picture", b"x", "text/plain", admin)).status == 400
    assert (await put(house, "/api/v1/door/picture", b"x" * (900 * 1024 + 1), "image/jpeg", admin)).status == 400
    assert (await house.client.delete("/api/v1/door/picture", headers={**admin.headers, "Origin": ORIGIN})).status == 204
    assert "door.picture" in await audit_actions(house)


async def test_greeting_text_window_and_sound(house, fake_ha):
    door(fake_ha)
    admin, _, _ = await people(house)
    body = {"enabled": True, "text": "Willkommen!", "start": "2026-10-21T13:00:00.000Z", "end": "2026-10-22T10:00:00.000Z"}
    r = await house.client.put("/api/v1/door/greeting", json=body, headers={**admin.headers, "Origin": ORIGIN})
    assert r.status == 204
    assert actions(fake_ha)[-1] == ("aikos", "door_greeting", {"enabled": True, "text": "Willkommen!",
                                                               "start": "2026-10-21T13:00:00.000Z",
                                                               "end": "2026-10-22T10:00:00.000Z", "voice": ""})
    r = await house.client.put("/api/v1/door/greeting", json={"always": True}, headers={**admin.headers, "Origin": ORIGIN})
    assert r.status == 204 and actions(fake_ha)[-1][2] == {"clear_window": True}
    r = await put(house, "/api/v1/door/greeting/audio", b"OggS-sound", "audio/ogg", admin)
    assert r.status == 204 and actions(fake_ha)[-1][2] == {"audio": "T2dnUy1zb3VuZA=="}
    r = await house.get("/api/v1/door/greeting/audio", admin)
    assert r.status == 200                                                          # through the app (resolve_media)
    r = await house.client.delete("/api/v1/door/greeting/audio", headers={**admin.headers, "Origin": ORIGIN})
    assert r.status == 204 and actions(fake_ha)[-1][2] == {"clear_audio": True}
    r = await house.client.put("/api/v1/door/greeting", json={"text": "x" * 121}, headers={**admin.headers, "Origin": ORIGIN})
    assert r.status == 400


async def test_without_aikos_0_9_the_app_says_so(house, fake_ha):
    admin, _, _ = await people(house)
    assert await (await house.get("/api/v1/door/actions", admin)).json() is None
    r = await house.post("/api/v1/door/bell", {"minutes": 60}, who=admin)
    assert r.status == 503 and (await r.json())["error"] == "no_door_actions"


async def test_status_shows_mute_end_and_quiet_switch(house, fake_ha):
    fake_ha.states["binary_sensor.aikos_bell_muted"] = {"state": "on", "attributes": {"until": "2026-10-21T16:00:00+02:00"}}
    fake_ha.states["switch.aikos_quiet_hours"] = {"state": "off", "attributes": {}}
    admin, _, _ = await people(house)
    s = await (await house.get("/api/v1/door/status", admin)).json()
    assert s["bell_muted"] is True and s["bell_muted_until"] == "2026-10-21T16:00:00+02:00" and s["quiet_enabled"] is False
