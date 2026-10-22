"""The live call (A47, A48): every ring a push to everyone who may act at the door (a storm of rings is one push); the
call at the door live in the app; talking to the door while held, through this node's RTP socket."""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import time

from conftest import ORIGIN, FakeHa, Household
from softauthn import SoftAuthenticator
from test_push import FakeSender, subscribe

from aikos_app.api.context import CTX
from aikos_app.talk import TalkBridge, audio_payload, swap16


async def people(house: Household):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    _, kim = await house.redeem(await house.invite(admin, "Kim", "child"), SoftAuthenticator(ORIGIN))
    return admin, sam, kim


def iso(ago_s: float = 0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - ago_s))


def ring(ha: FakeHa, when: str) -> None:
    ha._apply_entities({"a": {"sensor.aikos_door_ring": {"s": when, "a": {}}}})


async def settle(c) -> None:
    for t in list(c.ring_push._tasks):
        await t


async def test_every_ring_is_one_push_to_everyone_who_may_act_at_the_door(house, fake_ha):
    admin, sam, kim = await people(house)
    for who, name in ((admin, "admin"), (sam, "sam"), (kim, "kim")):
        await subscribe(house, who, name)
    c = house.client.app[CTX]
    c.door_push.sender = sender = FakeSender()
    c.ring_push.attach()
    ring(fake_ha, iso(1))
    await settle(c)
    assert sorted(e.rsplit("/", 1)[1] for e, _ in sender.sent) == ["admin", "sam"]   # the child gets none (2.4a)
    assert sender.sent[0][1]["kind"] == "ring"
    ring(fake_ha, iso(0))                                                            # ringing again: the same ring
    await settle(c)
    assert len(sender.sent) == 2
    assert await c.ring_push.notify(__import__("datetime").datetime.fromisoformat(iso(1))) == 0   # another node: claimed


async def test_an_old_ring_after_a_restart_gets_no_push(house, fake_ha):
    admin, _, _ = await people(house)
    await subscribe(house, admin, "admin")
    c = house.client.app[CTX]
    c.door_push.sender = sender = FakeSender()
    c.ring_push.attach()
    ring(fake_ha, iso(3600))
    await settle(c)
    assert sender.sent == []


async def test_the_call_at_the_door_live(house, fake_ha):
    admin, sam, kim = await people(house)
    fake_ha.states["sensor.aikos_call_log"] = {"state": "2026-10-22T10:00:00+00:00", "attributes": {
        "active": True, "call_id": "c7", "messages_json": json.dumps([
            {"id": "m1", "side": "door", "who": "Besucher", "text": "Hallo, ich habe ein Paket.", "tr": "", "tr_lang": ""},
            {"id": "m2", "side": "room", "who": "Sam", "text": "Komme sofort.", "tr": "", "tr_lang": ""}])}}
    fake_ha.states["sensor.aikos_door_ring"] = {"state": "2026-10-22T09:59:58+00:00", "attributes": {}}
    r = await (await house.get("/api/v1/door/call", sam)).json()
    assert r["active"] is True and r["call_id"] == "c7" and r["ring"] == "2026-10-22T09:59:58+00:00"
    assert [(m["side"], m["text"]) for m in r["messages"]] == [("door", "Hallo, ich habe ein Paket."), ("room", "Komme sofort.")]
    assert r["talk"] is False                                                        # not set up on this node
    assert (await house.get("/api/v1/door/call", kim)).status == 403
    fake_ha.states["sensor.aikos_call_log"]["attributes"]["messages_json"] = "not json"
    assert (await (await house.get("/api/v1/door/call", sam)).json())["messages"] == []


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def talk_actions(ha: FakeHa) -> list:
    return [(s, d) for dom, s, d in ha.services if dom == "esphome"]


async def recv_door(door: socket.socket, timeout: float = 2.0) -> bytes:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        try:
            return door.recv(4096)
        except BlockingIOError:
            await asyncio.sleep(0.01)
    raise AssertionError("nothing reached the door")


async def test_talking_to_the_door_while_held(house, fake_ha):
    _, sam, kim = await people(house)
    c = house.client.app[CTX]
    door = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    door.bind(("127.0.0.1", 0))
    door.setblocking(False)
    port = free_udp_port()
    c.talk = TalkBridge(fake_ha, "127.0.0.1", port, "127.0.0.1", door_port=door.getsockname()[1])
    await c.talk.start()
    try:
        hdr = {**sam.headers, "Origin": ORIGIN}
        assert (await house.client.get("/api/v1/door/talk", headers={**kim.headers, "Origin": ORIGIN})).status == 403
        assert (await house.client.get("/api/v1/door/talk", headers={**sam.headers, "Origin": "https://evil.example"})).status == 403
        ws = await house.client.ws_connect("/api/v1/door/talk", headers=hdr)
        assert (await ws.receive_json(timeout=2)) == {"state": "listening"}
        me = f"127.0.0.1:{port}"
        assert ("aikos_intercom_talk_app_join", {"host": me, "ms": 30000}) in talk_actions(fake_ha)
        assert ("aikos_intercom_talk_key_state", {"host": me, "state": 1}) in talk_actions(fake_ha)

        other = await house.client.ws_connect("/api/v1/door/talk", headers=hdr)        # one participant per node
        assert (await other.receive_json(timeout=2)) == {"state": "busy"}
        await other.close()

        await ws.send_str(json.dumps({"hold": True}))
        assert (await ws.receive_json(timeout=2)) == {"state": "talking"}
        assert ("aikos_intercom_talk_key_state", {"host": me, "state": 2}) in talk_actions(fake_ha)
        pcm = struct.pack("<320h", *range(320))                                         # 20 ms from the phone (LE)
        await ws.send_bytes(pcm)
        pkt = await recv_door(door)
        assert pkt[1] == 0x80 | 96 and pkt[12:] == swap16(pcm)                          # RTP, marker, big-endian
        await ws.send_str(json.dumps({"hold": False}))
        assert (await ws.receive_json(timeout=2)) == {"state": "listening"}
        assert (await recv_door(door))[1] & 0x7F == 13                                  # end of speech

        door_pcm = struct.pack(">320h", *range(0, 640, 2))                              # the door's mic (BE)
        door.sendto(struct.pack("!BBHII", 0x80, 96, 1, 0, 7) + door_pcm, ("127.0.0.1", port))
        got = await ws.receive(timeout=2)
        assert got.data == swap16(door_pcm)                                             # to the phone in LE
        await ws.close()
        for _ in range(300):
            if ("aikos_intercom_talk_app_join", {"host": "", "ms": 0}) in talk_actions(fake_ha):
                break
            await asyncio.sleep(0.01)
        assert ("aikos_intercom_talk_key_state", {"host": me, "state": 0}) in talk_actions(fake_ha)
        assert ("aikos_intercom_talk_app_join", {"host": "", "ms": 0}) in talk_actions(fake_ha)
        assert c.talk.session is None
    finally:
        c.talk.close()
        door.close()


def test_rtp_from_the_door_only_audio():
    assert audio_payload(struct.pack("!BBHII", 0x80, 96, 1, 0, 7) + b"\x00\x01") == b"\x00\x01"
    assert audio_payload(struct.pack("!BBHII", 0x80, 13, 1, 0, 7) + b"\x00") is None     # end-of-speech marker
    assert audio_payload(b"\x00" * 8) is None
    assert swap16(b"\x01\x02\x03\x04") == b"\x02\x01\x04\x03"


async def test_without_a_door_set_up_talking_is_off(house, fake_ha):
    _, sam, _ = await people(house)
    r = await house.client.get("/api/v1/door/talk", headers={**sam.headers, "Origin": ORIGIN})
    assert r.status == 503 and (await r.json())["error"] == "no_talk"
