"""Door messages: A10 (play through the app), A15 (visibility), G3 (no Home Assistant link or token on the phone),
A16 (Home Assistant keeps the data). Acceptance tests AT10a, AT15, AT16."""

from __future__ import annotations

import json

from conftest import ORIGIN, FakeHa, Household, make_settings
from softauthn import SoftAuthenticator

from aikos_app.api.server import create_app

T0 = 1792565255.0


def door_data(ha: FakeHa) -> None:
    ha.files = ["nachricht-20261021-084735.mp3", "nachricht-20261021-091936.mp3", "nachricht-20261021-101010.mp3",
                "zeichnung-1.png"]
    ha.history = {
        "sensor.aikos_test_last_message": [
            {"s": "nachricht-20261021-084735.mp3", "a": {"seconds": 8.3, "time": "2026-10-21T08:47:35+02:00"}, "lu": T0},
            {"s": "unavailable", "a": {}, "lu": T0 + 100},
            {"s": "nachricht-20261021-084735.mp3", "a": {"seconds": 8.3, "time": "2026-10-21T08:47:35+02:00"}, "lu": T0 + 101},
            {"s": "nachricht-20261021-091936.mp3", "a": {"seconds": 7.9, "recipient": "Sam",
                                                        "time": "2026-10-21T09:19:36+02:00"}, "lu": T0 + 1920},
            {"s": "nachricht-20261021-101010.mp3", "a": {"seconds": 4.0, "recipient": "Alex",
                                                        "time": "2026-10-21T10:10:10+02:00"}, "lu": T0 + 4950},
        ],
        "input_text.aikos_test_message_text": [
            {"s": "", "lu": T0 - 20}, {"s": "Paketdienst: Paket liegt in der Box.", "lu": T0 - 5},
            {"s": "", "lu": T0 + 1900}, {"s": "Nachbarin: Kannst du die Katze füttern?", "lu": T0 + 1918},
        ],
    }


async def people(house: Household):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    _, robin = await house.redeem(await house.invite(admin, "Robin", "adult"), SoftAuthenticator(ORIGIN))
    return admin, sam, robin


async def ids(house, person):
    return [m["id"] for m in await (await house.get("/api/v1/door/messages", person)).json()]


async def test_list_merges_media_and_interim_metadata(house, fake_ha):
    door_data(fake_ha)
    admin, _, _ = await people(house)
    msgs = await (await house.get("/api/v1/door/messages", admin)).json()
    assert [m["id"] for m in msgs] == ["nachricht-20261021-101010", "nachricht-20261021-091936", "nachricht-20261021-084735"]
    first = msgs[2]
    assert first["seconds"] == 8.3 and first["recipient"] == "" and first["text"] == "Paketdienst: Paket liegt in der Box."
    assert msgs[1]["recipient"] == "Sam" and msgs[1]["text"].startswith("Nachbarin:")
    assert first["audio"] == "/api/v1/door/messages/nachricht-20261021-084735/audio"


async def test_back_to_back_messages_keep_their_own_text(house, fake_ha):
    """Regression (ha-dev 21.10.): two messages a minute apart; the first must not get the second's words."""
    fake_ha.files = ["nachricht-20261021-084635.mp3", "nachricht-20261021-084735.mp3"]
    t1, t2 = T0 - 60, T0
    fake_ha.history = {
        "sensor.aikos_test_last_message": [{"s": "nachricht-20261021-084635.mp3", "a": {"seconds": 9.2}, "lu": t1},
                                     {"s": "nachricht-20261021-084735.mp3", "a": {"seconds": 8.3}, "lu": t2}],
        "input_text.aikos_test_message_text": [{"s": "", "lu": t1 - 14}, {"s": "Erste Nachricht.", "lu": t1 - 5},
                                         {"s": "", "lu": t2 - 13}, {"s": "Zweite Nachricht.", "lu": t2 - 6}],
    }
    admin, _, _ = await people(house)
    msgs = {m["id"]: m["text"] for m in await (await house.get("/api/v1/door/messages", admin)).json()}
    assert msgs == {"nachricht-20261021-084635": "Erste Nachricht.", "nachricht-20261021-084735": "Zweite Nachricht."}


async def test_a15_visibility(house, fake_ha):
    door_data(fake_ha)
    admin, sam, robin = await people(house)
    assert len(await ids(house, admin)) == 3
    assert await ids(house, sam) == ["nachricht-20261021-091936", "nachricht-20261021-084735"]
    assert await ids(house, robin) == ["nachricht-20261021-084735"]


async def test_someone_elses_message_does_not_exist(house, fake_ha):
    door_data(fake_ha)
    _, sam, robin = await people(house)
    r = await house.get("/api/v1/door/messages/nachricht-20261021-091936/audio", robin)
    assert r.status == 404
    r = await house.get("/api/v1/door/messages/nachricht-20261021-091936/audio", sam)
    assert r.status == 200 and r.headers["Content-Type"] == "audio/mpeg"
    assert await r.read() == fake_ha.audio


async def test_audio_supports_range(house, fake_ha):
    door_data(fake_ha)
    admin, _, _ = await people(house)
    r = await house.get("/api/v1/door/messages/nachricht-20261021-084735/audio", admin, headers={"Range": "bytes=100-"})
    assert r.status == 206 and r.headers["Content-Range"].startswith("bytes 100-")
    assert await r.read() == fake_ha.audio[100:]


async def test_phone_never_sees_home_assistant(house, fake_ha):
    door_data(fake_ha)
    admin, _, _ = await people(house)
    listing = await (await house.get("/api/v1/door/messages", admin)).text()
    r = await house.get("/api/v1/door/messages/nachricht-20261021-084735/audio", admin)
    everything = listing + json.dumps(dict(r.headers))
    for leak in ("authSig", "SIGNATURE", "/media/local", "ha.invalid", "token-that-must-not-leak"):
        assert leak not in everything


async def test_bad_message_ids(house, fake_ha):
    door_data(fake_ha)
    admin, _, _ = await people(house)
    for bad in ("..%2Fsecrets", "zeichnung-1", "nope"):
        assert (await house.get(f"/api/v1/door/messages/{bad}/audio", admin)).status == 404


async def test_signed_out_gets_nothing(house, fake_ha):
    door_data(fake_ha)
    assert (await house.get("/api/v1/door/messages")).status == 401
    assert (await house.get("/api/v1/door/messages/nachricht-20261021-084735/audio")).status == 401
    assert fake_ha.asked == []


async def test_a16_data_stays_in_home_assistant(tmp_path, aiohttp_client):
    """Wiping the app's database loses accounts only; the messages come back from Home Assistant."""
    ha = FakeHa()
    door_data(ha)
    sa = make_settings(tmp_path / "a")  # once: with rqlite every call empties the shared database
    first = Household(await aiohttp_client(create_app(sa, ha=ha)), sa)
    _, m1 = await first.setup(SoftAuthenticator(ORIGIN))
    before = await ids(first, m1)
    sb = make_settings(tmp_path / "b")
    second = Household(await aiohttp_client(create_app(sb, ha=ha)), sb)
    _, m2 = await second.setup(SoftAuthenticator(ORIGIN))
    assert await ids(second, m2) == before and len(before) == 3


async def test_status(house, fake_ha):
    admin, _, _ = await people(house)
    fake_ha.states = {
        "binary_sensor.aikos_intercom_screen_someone_at_the_door": {"state": "on", "attributes": {}, "last_changed": T0},
        "binary_sensor.aikos_quiet_hours": {"state": "off", "attributes": {"start": "20:00", "end": "07:00"}},
    }
    s = await (await house.get("/api/v1/door/status", admin)).json()
    assert s["someone_at_door"] is True and s["someone_since"] == T0
    assert s["quiet_hours"] is False and s["quiet_start"] == "20:00" and s["bell_muted"] is None
