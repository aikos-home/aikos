"""Door messages from the aikos message register (aikos 0.8.0): list with words, speaker and "heard"; delete for good (A38),
heard (kept in Home Assistant), forward by hand (A37). The rights are checked in the app before Home Assistant is asked."""

from __future__ import annotations

from conftest import ORIGIN, FakeHa, Household
from softauthn import SoftAuthenticator

from aikos_app.api.context import CTX
from aikos_app.roles import Role, may_delete_message

T0 = 1792565255.0


def msg(stamp: str, recipient: str = "", **kw) -> dict:
    return {"id": f"nachricht-{stamp}", "file": f"nachricht-{stamp}.mp3", "time": kw.pop("time", "2026-10-21T08:47:15+00:00"),
            "seconds": 8.3, "recipient": recipient, "text": "", "speaker": "", "heard_by": [], "adopted": False,
            "file_missing": False, **kw}


def register(ha: FakeHa) -> None:
    ha.use_register([
        msg("20261021-084735", text="Paket liegt in der Box.", speaker="Paketdienst", time="2026-10-21T06:47:40+00:00"),
        msg("20261021-091936", "Sam", text="Kannst du die Katze füttern?", time="2026-10-21T07:19:40+00:00"),
        msg("20261021-101010", "Alex", time="2026-10-21T08:10:15+00:00", heard_by=["Alex"]),
    ])


def writes(ha: FakeHa) -> list:
    return [s for s in ha.services if s[1] != "door_messages"]


async def people(house: Household):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))  # "Alex", superadmin
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    _, robin = await house.redeem(await house.invite(admin, "Robin", "adult"), SoftAuthenticator(ORIGIN))
    return admin, sam, robin


async def listing(house, who):
    return {m["id"]: m for m in await (await house.get("/api/v1/door/messages", who)).json()}


async def test_list_comes_from_the_register_with_words_speaker_and_heard(house, fake_ha):
    register(fake_ha)
    admin, sam, robin = await people(house)
    mine = await listing(house, admin)
    assert list(mine) == ["nachricht-20261021-101010", "nachricht-20261021-091936", "nachricht-20261021-084735"]
    first = mine["nachricht-20261021-084735"]
    assert (first["text"], first["speaker"], first["recipient"], first["seconds"]) == (
        "Paket liegt in der Box.", "Paketdienst", "", 8.3)
    assert first["audio"] == "/api/v1/door/messages/nachricht-20261021-084735/audio" and first["audio_missing"] is False
    assert mine["nachricht-20261021-101010"]["heard"] is True and first["heard"] is False
    assert "file" not in first and "media_source/browse_media" not in fake_ha.asked   # the register, not the folder
    assert list(await listing(house, sam)) == ["nachricht-20261021-091936", "nachricht-20261021-084735"]  # A15 unchanged
    assert list(await listing(house, robin)) == ["nachricht-20261021-084735"]


async def test_adopted_messages_get_the_interim_text(house, fake_ha):
    fake_ha.use_register([msg("20261021-084735", adopted=True, seconds=None, time="2026-10-21T06:47:35+00:00")])
    fake_ha.history = {
        "sensor.aikos_test_last_message": [{"s": "nachricht-20261021-084735.mp3",
                                            "a": {"seconds": 8.3, "recipient": "", "time": "2026-10-21T08:47:35+02:00"},
                                            "lu": T0}],
        "input_text.aikos_test_message_text": [{"s": "", "lu": T0 - 20}, {"s": "Paketdienst: Paket liegt in der Box.", "lu": T0 - 5}],
    }
    admin, _, _ = await people(house)
    [m] = (await listing(house, admin)).values()
    assert m["text"] == "Paketdienst: Paket liegt in der Box." and m["seconds"] == 8.3


async def test_a_message_whose_file_is_gone_has_no_audio(house, fake_ha):
    fake_ha.use_register([msg("20261021-084735", file_missing=True)])
    admin, _, _ = await people(house)
    [m] = (await listing(house, admin)).values()
    assert m["audio"] is None and m["audio_missing"] is True and m["may_delete"] is True
    assert (await house.get("/api/v1/door/messages/nachricht-20261021-084735/audio", admin)).status == 404


async def test_a38_who_may_delete(house, fake_ha):
    register(fake_ha)
    admin, sam, robin = await people(house)
    flags = {i: m["may_delete"] for i, m in (await listing(house, robin)).items()}
    assert flags == {"nachricht-20261021-084735": True}                       # for everyone: every adult
    assert (await house.delete("/api/v1/door/messages/nachricht-20261021-091936", robin)).status == 404  # Sam's: not there
    assert (await house.delete("/api/v1/door/messages/nachricht-20261021-091936", sam)).status == 204    # the recipient
    assert (await house.delete("/api/v1/door/messages/nachricht-20261021-101010", admin)).status == 204  # the superadmin
    assert writes(fake_ha) == [("aikos", "door_message_delete", {"id": "nachricht-20261021-091936", "by": "Sam"}),
                                ("aikos", "door_message_delete", {"id": "nachricht-20261021-101010", "by": "Alex"})]
    assert list(await listing(house, admin)) == ["nachricht-20261021-084735"]
    audit = [(a["action"], a["ok"], a["target"]) for a in house.client.app[CTX].audit.recent()
             if a["action"] == "message.delete"]
    assert sorted(audit) == [("message.delete", 1, "nachricht-20261021-091936"), ("message.delete", 1, "nachricht-20261021-101010")]


def test_a38_children_delete_only_their_own():
    assert may_delete_message(Role.CHILD, ["Kim"], "Kim")
    assert not may_delete_message(Role.CHILD, ["Kim"], "")          # for everyone: adults and the superadmin only
    assert not may_delete_message(Role.CHILD, ["Kim"], "Sam")
    assert may_delete_message(Role.ADULT, ["Sam"], "") and may_delete_message(Role.SUPERADMIN, [], "Sam")
    assert not may_delete_message(Role.ADULT, ["Robin"], "Sam")


async def test_delete_needs_the_same_origin(house, fake_ha):
    register(fake_ha)
    admin, _, _ = await people(house)
    r = await house.delete("/api/v1/door/messages/nachricht-20261021-084735", admin, origin="https://evil.example")
    assert r.status == 403 and writes(fake_ha) == []


async def test_heard_goes_to_home_assistant_once(house, fake_ha):
    register(fake_ha)
    _, sam, _ = await people(house)
    for _ in range(2):
        r = await house.post("/api/v1/door/messages/nachricht-20261021-091936/heard", who=sam)
        assert r.status == 204
    assert writes(fake_ha) == [("aikos", "door_message_heard", {"id": "nachricht-20261021-091936", "by": "Sam"})]
    assert (await listing(house, sam))["nachricht-20261021-091936"]["heard"] is True
    assert (await house.post("/api/v1/door/messages/nachricht-20261021-101010/heard", who=sam)).status == 404


async def test_share_is_a_file_and_recorded(house, fake_ha):
    register(fake_ha)
    _, sam, _ = await people(house)
    r = await house.get("/api/v1/door/messages/nachricht-20261021-091936/audio?share=1", sam)
    assert r.status == 200 and await r.read() == fake_ha.audio
    assert r.headers["Content-Disposition"] == 'attachment; filename="aikos-nachricht-20261021-091936.mp3"'
    actions = [a["action"] for a in house.client.app[CTX].audit.recent()]
    assert "message.share" in actions and "message.play" not in actions


async def test_without_the_register_delete_and_heard_say_so(house, fake_ha):
    fake_ha.files = ["nachricht-20261021-084735.mp3"]
    admin, _, _ = await people(house)
    r = await house.delete("/api/v1/door/messages/nachricht-20261021-084735", admin)
    assert r.status == 503 and (await r.json())["error"] == "no_register"
    r = await house.post("/api/v1/door/messages/nachricht-20261021-084735/heard", who=admin)
    assert r.status == 503


async def test_order_follows_the_instant_not_the_text(house, fake_ha):
    """Regression (ha-dev 21.10.): an adopted message's interim time "13:29+02:00" sorted above a newer register
    time "12:06+00:00" because the texts were compared."""
    fake_ha.use_register([msg("20261021-132957", adopted=True, time="2026-10-21T11:29:57+00:00"),
                          msg("20261021-140900", time="2026-10-21T12:06:00+00:00")])
    fake_ha.history = {"sensor.aikos_test_last_message": [
        {"s": "nachricht-20261021-132957.mp3", "a": {"seconds": 4, "time": "2026-10-21T13:29:57+02:00"}, "lu": T0}]}
    admin, _, _ = await people(house)
    assert list(await listing(house, admin)) == ["nachricht-20261021-140900", "nachricht-20261021-132957"]
