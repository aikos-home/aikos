"""Rule A2 (passkey sign-in only), invites, sessions, same-origin writes (acceptance test AT2)."""

from __future__ import annotations

import time

from conftest import ORIGIN, person_of
from softauthn import SoftAuthenticator

from aikos_app.store import accounts as accounts_mod


async def test_setup_creates_the_superadmin_once(house):
    assert (await (await house.get("/api/v1/setup")).json()) == {"needs_setup": True}
    r, admin = await house.setup(SoftAuthenticator(ORIGIN))
    assert r.status == 200 and admin
    me = await (await house.get("/api/v1/me", admin)).json()
    assert me["name"] == "Alex" and me["role"] == "superadmin"
    assert (await (await house.get("/api/v1/setup")).json()) == {"needs_setup": False}
    r = await house.post("/api/v1/setup/start", {"code": "AAAA-BBBB-CCCC", "name": "X"})
    assert r.status == 409


async def test_wrong_setup_code_is_refused(house):
    r = await house.post("/api/v1/setup/start", {"code": "AAAA-BBBB-CCCC", "name": "Alex"})
    assert r.status == 400 and (await r.json())["error"] == "invalid_code"


async def test_session_cookie_is_httponly_secure_strict(house):
    r, _ = await house.setup(SoftAuthenticator(ORIGIN))
    raw = r.headers.getall("Set-Cookie")[0]
    assert "HttpOnly" in raw and "Secure" in raw and "SameSite=Strict" in raw
    assert "token" not in await r.json()


async def test_login_logout(house):
    authn = SoftAuthenticator(ORIGIN)
    await house.setup(authn)
    r, admin = await house.login(authn)
    assert r.status == 200 and admin
    assert (await house.get("/api/v1/me", admin)).status == 200
    assert (await house.post("/api/v1/logout", who=admin)).status == 200
    assert (await house.get("/api/v1/me", admin)).status == 401


async def test_challenge_is_single_use(house):
    authn = SoftAuthenticator(ORIGIN)
    await house.setup(authn)
    start = await (await house.post("/api/v1/login/start")).json()
    cred = authn.get(start["options"])
    assert (await house.post("/api/v1/login/finish", {"flow": start["flow"], "credential": cred})).status == 200
    r = await house.post("/api/v1/login/finish", {"flow": start["flow"], "credential": cred})
    assert r.status == 400 and (await r.json())["error"] == "flow_expired"


async def test_passkey_from_another_origin_is_refused(house):
    authn = SoftAuthenticator(ORIGIN)
    await house.setup(authn)
    start = await (await house.post("/api/v1/login/start")).json()
    cred = authn.get(start["options"], origin="https://evil.example")
    r = await house.post("/api/v1/login/finish", {"flow": start["flow"], "credential": cred})
    assert r.status == 400 and (await r.json())["error"] == "passkey_failed"


async def test_user_verification_is_required(house):
    r = await house.post("/api/v1/setup/start", {"code": house.setup_code(), "name": "Alex"})
    start = await r.json()
    cred = SoftAuthenticator(ORIGIN, user_verified=False).create(start["options"])
    r = await house.post("/api/v1/setup/finish", {"flow": start["flow"], "credential": cred})
    assert r.status == 400 and (await r.json())["error"] == "passkey_failed"


async def test_unknown_passkey_is_refused(house):
    await house.setup(SoftAuthenticator(ORIGIN))
    stranger = SoftAuthenticator(ORIGIN)
    start = await (await house.post("/api/v1/login/start")).json()
    stranger.create({"rp": {"id": "localhost"}, "user": {"id": "AAAA"}, "challenge": start["options"]["challenge"]})
    r = await house.post("/api/v1/login/finish", {"flow": start["flow"], "credential": stranger.get(start["options"])})
    assert r.status == 400 and (await r.json())["error"] == "unknown_passkey"


async def test_synced_passkeys_without_counter_work(house):
    authn = SoftAuthenticator(ORIGIN, counter=False)
    await house.setup(authn)
    assert (await house.login(authn))[0].status == 200
    assert (await house.login(authn))[0].status == 200


async def test_invite_creates_person_once(house):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    token = await house.invite(admin, "Sam", "adult", "person.aikos_test_sam")
    info = await (await house.post("/api/v1/invites/info", {"token": token})).json()
    assert info["name"] == "Sam" and info["role"] == "adult" and info["kind"] == "new"
    r, sam = await house.redeem(token, SoftAuthenticator(ORIGIN))
    assert r.status == 200
    me = await (await house.get("/api/v1/me", sam)).json()
    assert me["role"] == "adult" and me["ha_person"] == "person.aikos_test_sam"
    r = await house.post("/api/v1/invites/start", {"token": token})
    assert r.status == 400 and (await r.json())["error"] == "invite_invalid"


async def test_expired_invite_is_refused(house, monkeypatch):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    token = await house.invite(admin, "Sam", "adult")
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + accounts_mod.INVITE_TTL_S + 5)
    r = await house.post("/api/v1/invites/start", {"token": token})
    assert r.status == 400 and (await r.json())["error"] == "invite_invalid"


async def test_adult_cannot_invite(house):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    r = await house.post("/api/v1/people/invites", {"name": "Eve", "role": "superadmin"}, who=sam)
    assert r.status == 403
    assert (await house.get("/api/v1/people", sam)).status == 403


async def test_device_invite_adds_a_passkey_to_the_same_person(house):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    sam_id = (await (await house.get("/api/v1/me", sam)).json())["id"]
    link = await (await house.post(f"/api/v1/people/{sam_id}/device-invite", who=admin)).json()
    new_phone = SoftAuthenticator(ORIGIN)
    r, sam2 = await house.redeem(link["link"].split("#", 1)[1], new_phone)
    assert r.status == 200
    assert (await (await house.get("/api/v1/me", sam2)).json())["id"] == sam_id
    assert len(await (await house.get("/api/v1/me/passkeys", sam2)).json()) == 2


async def test_last_passkey_cannot_be_deleted(house):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    keys = await (await house.get("/api/v1/me/passkeys", admin)).json()
    r = await house.client.delete(f"/api/v1/me/passkeys/{keys[0]['id']}", headers={**admin.headers, "Origin": ORIGIN})
    assert r.status == 409


async def test_writes_need_the_app_origin(house):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    r = await house.post("/api/v1/people/invites", {"name": "Eve", "role": "adult"}, who=admin, origin=None)
    assert r.status == 403 and (await r.json())["error"] == "bad_origin"
    r = await house.post("/api/v1/people/invites", {"name": "Eve", "role": "adult"}, who=admin,
                         origin="https://evil.example")
    assert r.status == 403


async def test_native_client_gets_a_bearer_token(house):
    authn = SoftAuthenticator(ORIGIN)
    await house.setup(authn)
    native = {"X-Aikos-Client": "native"}
    start = await (await house.post("/api/v1/login/start", headers=native, origin=None)).json()
    r = await house.post("/api/v1/login/finish", {"flow": start["flow"], "credential": authn.get(start["options"])},
                         headers=native, origin=None)
    body = await r.json()
    assert r.status == 200 and body["token"] and person_of(r) is None
    me = await house.get("/api/v1/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert (await me.json())["name"] == "Alex"


async def test_disabled_person_loses_sessions(house):
    _, admin = await house.setup(SoftAuthenticator(ORIGIN))
    _, sam = await house.redeem(await house.invite(admin, "Sam", "adult"), SoftAuthenticator(ORIGIN))
    sam_id = (await (await house.get("/api/v1/me", sam)).json())["id"]
    assert (await house.post(f"/api/v1/people/{sam_id}/disable", who=admin)).status == 200
    assert (await house.get("/api/v1/me", sam)).status == 401


async def test_sign_in_brake(house):
    for _ in range(30):
        await house.post("/api/v1/setup/start", {"code": "x", "name": "y"})
    r = await house.post("/api/v1/setup/start", {"code": "x", "name": "y"})
    assert r.status == 429


async def test_security_headers(house):
    r = await house.get("/api/v1/health")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Cache-Control"] == "no-store"
