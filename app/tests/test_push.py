"""Push (rules A15, A24, G5): encryption per RFC 8291, VAPID per RFC 8292, only known push services as targets, a new door
message goes once (of three nodes) to exactly the people who may see it, never with sound."""

from __future__ import annotations

import json
import os
import time

import pytest
from conftest import ORIGIN, Household, fresh_db
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from softauthn import SoftAuthenticator

from aikos_app.api.context import CTX
from aikos_app.push.sender import endpoint_allowed
from aikos_app.push.webpush import b64u, encrypt, new_vapid_key, unb64u, vapid_authorization, vapid_public
from aikos_app.store.push import Pushes

FCM = "https://fcm.googleapis.com/fcm/send/"


def phone_keys() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return b64u(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)), b64u(os.urandom(16))


def test_encryption_matches_the_rfc_8291_example():
    sender = ec.derive_private_key(int.from_bytes(unb64u("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
                                   ec.SECP256R1())
    body = encrypt(b"When I grow up, I want to be a watermelon",
                   "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                   "BTBZMqHH6r4Tts7J_aSIgg", salt=unb64u("DGv6ra1nlYgDCS1FRnbzlw"), sender_key=sender)
    assert b64u(body) == ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEq"
                          "KK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def test_vapid_token_is_signed_for_the_push_service_and_short_lived():
    private = new_vapid_key()
    header = vapid_authorization(FCM + "abc", private, ORIGIN, now=1_000_000)
    token, k = header.removeprefix("vapid t=").split(", k=")
    head, claims, sig = token.split(".")
    assert k == vapid_public(private)
    c = json.loads(unb64u(claims))
    assert c == {"aud": "https://fcm.googleapis.com", "exp": 1_000_000 + 12 * 3600, "sub": ORIGIN}
    raw = unb64u(sig)
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(k))
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        public.verify(der, f"{head}.{claims}x".encode(), ec.ECDSA(hashes.SHA256()))


@pytest.mark.parametrize("endpoint,ok", [
    (FCM + "x", True), ("https://web.push.apple.com/QGx", True), ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
    ("https://wns2-db5p.notify" ".windows.com/w/?token=x", True),
    ("http://fcm.googleapis.com/x", False), ("https://203.0.113.7/x", False), ("https://fcm.googleapis.com.evil.example/x", False),
    ("https://evilfcm.googleapis.com.example/x", False), ("https://user:pw" "@fcm.googleapis.com/x", False),
    ("https://fcm.googleapis.com:8443/x", False), ("https://localhost/x", False), ("not a url", False),
])
def test_only_known_push_services_are_targets(endpoint, ok):
    assert endpoint_allowed(endpoint) is ok


def test_the_vapid_key_is_shared_through_the_database(tmp_path):
    db = fresh_db(tmp_path)
    a, b = Pushes(db).vapid_private(new_vapid_key()), Pushes(db).vapid_private(new_vapid_key())
    assert a == b
    db.close()


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.answer = "ok"

    async def send(self, endpoint, p256dh, auth, payload, **kw):
        self.sent.append((endpoint, payload))
        return self.answer

    async def close(self):
        pass


async def people(house: Household):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    _, robin = await house.redeem(await house.invite(admin, "Robin", "adult"), SoftAuthenticator(ORIGIN))
    return admin, sam, robin


async def subscribe(house, who, name):
    p256dh, auth = phone_keys()
    r = await house.post("/api/v1/push/subscription", {"endpoint": FCM + name, "keys": {"p256dh": p256dh, "auth": auth}},
                         who=who)
    assert r.status == 200, await r.text()


def now_iso(ago_s: float = 0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - ago_s))


def register_message(ha, stamp, recipient="", ago_s=0.0, **kw):
    entry = {"id": f"nachricht-{stamp}", "file": f"nachricht-{stamp}.mp3", "time": now_iso(ago_s), "seconds": 9.4,
             "recipient": recipient, "text": "Paket liegt in der Box.", "speaker": "Paketdienst", "heard_by": [],
             "adopted": False, "file_missing": False, **kw}
    ha.use_register((ha.register or []) + [entry])
    return entry["id"]


async def test_subscription_api_checks_target_and_keys(house):
    admin, _, _ = await people(house)
    assert (await (await house.get("/api/v1/push/key", admin)).json())["key"]
    p256dh, auth = phone_keys()
    for body in ({"endpoint": "https://203.0.113.7/x", "keys": {"p256dh": p256dh, "auth": auth}},
                 {"endpoint": FCM + "x", "keys": {"p256dh": "AAAA", "auth": auth}},
                 {"endpoint": FCM + "x", "keys": {"p256dh": p256dh, "auth": "short"}}, ["not", "an", "object"]):
        r = await house.post("/api/v1/push/subscription", body, who=admin)
        assert r.status == 400
    await subscribe(house, admin, "a")
    await subscribe(house, admin, "a")                                          # the same phone again: still one
    pushes = house.client.app[CTX].pushes
    assert [s.endpoint for s in pushes.of_user(1)] == [FCM + "a"]
    r = await house.client.delete("/api/v1/push/subscription", json={"endpoint": FCM + "a"},
                                  headers={**admin.headers, "Origin": ORIGIN})
    assert r.status == 200 and pushes.of_user(1) == []
    assert (await house.get("/api/v1/push/key")).status == 401


async def test_a_new_message_goes_to_exactly_the_people_who_may_see_it_once(house, fake_ha):
    admin, sam, robin = await people(house)
    for who, name in ((admin, "admin"), (sam, "sam"), (robin, "robin")):
        await subscribe(house, who, name)
    c = house.client.app[CTX]
    c.door_push.sender = sender = FakeSender()
    msg_id = register_message(fake_ha, "20261021-140000", "Sam")
    fake_ha.states["binary_sensor.aikos_test_someone"] = {"state": "on"}
    c.door_push.someone_entity = "binary_sensor.aikos_test_someone"
    assert await c.door_push.notify(msg_id) == 2
    assert sorted(e.rsplit("/", 1)[1] for e, _ in sender.sent) == ["admin", "sam"]   # not Robin (A15)
    data = sender.sent[0][1]
    assert data == {"kind": "door_message", "id": msg_id, "time": data["time"], "seconds": 9.4, "recipient": "Sam",
                    "speaker": "Paketdienst", "text": "Paket liegt in der Box.", "here": True}   # no sound, no link (G5)
    assert await c.door_push.notify(msg_id) == 0                                     # another node: already claimed


async def test_old_messages_get_no_push_and_gone_phones_are_forgotten(house, fake_ha):
    admin, _, _ = await people(house)
    await subscribe(house, admin, "admin")
    c = house.client.app[CTX]
    c.door_push.sender = sender = FakeSender()
    assert await c.door_push.notify(register_message(fake_ha, "20261021-120000", ago_s=3600)) == 0
    sender.answer = "gone"
    assert await c.door_push.notify(register_message(fake_ha, "20261021-140100")) == 0
    assert c.pushes.of_user(1) == []


async def test_the_register_change_triggers_the_push(house, fake_ha, monkeypatch):
    import aikos_app.push.door_push as dp
    monkeypatch.setattr(dp, "WAIT_FOR_WORDS_S", 0)
    admin, _, _ = await people(house)
    await subscribe(house, admin, "admin")
    c = house.client.app[CTX]
    c.door_push.sender = sender = FakeSender()
    msg_id = register_message(fake_ha, "20261021-140200")
    c.door_push.attach()
    fake_ha._apply_entities({"a": {"sensor.aikos_door_messages": {"s": "1", "a": {"newest": msg_id, "revision": 1}}}})
    fake_ha._apply_entities({"c": {"sensor.aikos_door_messages": {"+": {"a": {"revision": 2}}}}})  # heard: no new push
    for t in list(c.door_push._tasks):
        await t
    assert [p["id"] for _, p in sender.sent] == [msg_id]


async def test_test_push_reaches_my_own_phones_only(house):
    admin, sam, _ = await people(house)
    await subscribe(house, admin, "admin")
    await subscribe(house, sam, "sam")
    c = house.client.app[CTX]
    c.door_push.sender = sender = FakeSender()
    r = await house.post("/api/v1/push/test", who=sam)
    assert (await r.json())["sent"] == 1 and sender.sent == [(FCM + "sam", {"kind": "test"})]
