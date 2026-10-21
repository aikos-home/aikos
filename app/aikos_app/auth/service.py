"""Who may become who: setup code → first person (superadmin), invites → further people or devices, login.

No web framework here; the API layer only translates HTTP into these calls.
"""

from __future__ import annotations

import base64
from typing import Any

from ..roles import Cap, Role, can
from ..store.accounts import Accounts, Invite, User, normalize_code
from ..store.audit import Audit
from ..store.flows import Flows
from ..store.sessions import Sessions
from .passkeys import PasskeyError, Passkeys

NAME_MAX = 40


class AuthError(Exception):
    """`code` is stable and machine-readable; the app shows its own words for it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > NAME_MAX:
        raise AuthError("invalid_name")
    return name


class AuthService:
    def __init__(self, accounts: Accounts, sessions: Sessions, flows: Flows, audit: Audit, passkeys: Passkeys) -> None:
        self.accounts, self.sessions, self.flows, self.audit, self.passkeys = accounts, sessions, flows, audit, passkeys

    # first start
    def needs_setup(self) -> bool:
        return self.accounts.count_users() == 0

    def new_setup_code(self) -> str | None:
        """A fresh one-time code while nobody exists yet; None once the first person is there."""
        return self.accounts.new_setup_code() if self.needs_setup() else None

    def setup_start(self, code: str, name: str, ip: str = "") -> tuple[str, dict[str, Any]]:
        if not self.needs_setup():
            raise AuthError("already_set_up")
        name = _clean_name(name)
        if not self.accounts.setup_code_valid(code):
            self.audit.log("setup.start", False, ip=ip)
            raise AuthError("invalid_code")
        handle = self.accounts.new_handle()
        options, challenge = self.passkeys.registration(handle, name, [])
        flow = self.flows.start("setup", challenge, {"handle": _b64(handle), "name": name, "code": normalize_code(code)})
        return flow, options

    def setup_finish(self, flow_id: str, credential: dict[str, Any], label: str = "", ip: str = "") -> tuple[User, str]:
        flow = self.flows.take(flow_id, "setup")
        if flow is None:
            raise AuthError("flow_expired")
        if not self.needs_setup():
            raise AuthError("already_set_up")
        cred = self._verify_registration(credential, flow.challenge, label)
        if not self.accounts.use_setup_code(flow.data["code"]):
            raise AuthError("invalid_code")
        user = self.accounts.create_user_with_credential(_unb64(flow.data["handle"]), flow.data["name"],
                                                         Role.SUPERADMIN, "", cred)
        self.audit.log("setup.finish", True, user.id, ip=ip)
        return user, self.sessions.create(user.id, label)

    # invites
    def create_invite(self, actor: User, name: str, role: str, ha_person: str = "") -> tuple[str, Invite]:
        if not can(actor.role, Cap.PEOPLE_MANAGE):
            raise AuthError("forbidden")
        try:
            role = Role(role)
        except ValueError:
            raise AuthError("invalid_role") from None
        token, invite = self.accounts.create_invite(_clean_name(name), role, (ha_person or "").strip()[:80], actor.id)
        self.audit.log("invite.create", True, actor.id, target=f"{invite.id}:{role}")
        return token, invite

    def device_invite(self, user_id: int, created_by: int | None = None) -> tuple[str, Invite]:
        """An invite that adds a passkey to an existing person (new phone, lost phone). Also used by the recovery CLI."""
        user = self.accounts.get_user(user_id)
        if user is None or user.disabled:
            raise AuthError("unknown_user")
        token, invite = self.accounts.create_invite(user.name, user.role, user.ha_person, created_by, user_id=user.id)
        self.audit.log("invite.device", True, created_by, target=str(user.id))
        return token, invite

    def invite_info(self, token: str) -> Invite:
        invite = self.accounts.open_invite(token)
        if invite is None:
            raise AuthError("invite_invalid")
        return invite

    def invite_start(self, token: str, ip: str = "") -> tuple[str, dict[str, Any], Invite]:
        invite = self.accounts.open_invite(token)
        if invite is None:
            self.audit.log("invite.start", False, ip=ip)
            raise AuthError("invite_invalid")
        if invite.user_id is not None:
            user = self.accounts.get_user(invite.user_id)
            if user is None or user.disabled:
                raise AuthError("invite_invalid")
            handle, existing = user.handle, self.accounts.credentials_of(user.id)
        else:
            handle, existing = self.accounts.new_handle(), []
        options, challenge = self.passkeys.registration(handle, invite.name, existing)
        flow = self.flows.start("invite", challenge, {"invite_id": invite.id, "handle": _b64(handle)})
        return flow, options, invite

    def invite_finish(self, flow_id: str, credential: dict[str, Any], label: str = "", ip: str = "") -> tuple[User, str]:
        flow = self.flows.take(flow_id, "invite")
        if flow is None:
            raise AuthError("flow_expired")
        invite = self.accounts.open_invite_by_id(flow.data["invite_id"])
        if invite is None:
            raise AuthError("invite_invalid")
        cred = self._verify_registration(credential, flow.challenge, label)
        if not self.accounts.use_invite(invite.id):
            raise AuthError("invite_invalid")
        if invite.user_id is not None:
            self.accounts.add_credential(invite.user_id, cred)
            user = self.accounts.get_user(invite.user_id)
        else:
            user = self.accounts.create_user_with_credential(_unb64(flow.data["handle"]), invite.name, invite.role,
                                                             invite.ha_person, cred)
        self.audit.log("invite.finish", True, user.id, target=str(invite.id), ip=ip)
        return user, self.sessions.create(user.id, label)

    # login
    def login_start(self) -> tuple[str, dict[str, Any]]:
        options, challenge = self.passkeys.authentication()
        return self.flows.start("login", challenge), options

    def login_finish(self, flow_id: str, credential: dict[str, Any], label: str = "", ip: str = "") -> tuple[User, str]:
        flow = self.flows.take(flow_id, "login")
        if flow is None:
            raise AuthError("flow_expired")
        try:
            cred_id, handle = self.passkeys.identify(credential)
        except PasskeyError:
            raise AuthError("passkey_failed") from None
        stored = self.accounts.credential(cred_id)
        user = self.accounts.get_user(stored.user_id) if stored else None
        if stored is None or user is None or user.disabled or (handle and handle != user.handle):
            self.audit.log("login", False, ip=ip)
            raise AuthError("unknown_passkey")
        try:
            count = self.passkeys.verify_authentication(credential, flow.challenge, stored)
        except PasskeyError:
            self.audit.log("login", False, user.id, ip=ip)
            raise AuthError("passkey_failed") from None
        self.accounts.touch_credential(stored.id, count)
        self.audit.log("login", True, user.id, ip=ip)
        return user, self.sessions.create(user.id, label)

    # more passkeys for a signed-in person
    def add_passkey_start(self, user: User) -> tuple[str, dict[str, Any]]:
        options, challenge = self.passkeys.registration(user.handle, user.name, self.accounts.credentials_of(user.id))
        return self.flows.start("add_passkey", challenge, {"user_id": user.id}), options

    def add_passkey_finish(self, user: User, flow_id: str, credential: dict[str, Any], label: str = "") -> None:
        flow = self.flows.take(flow_id, "add_passkey")
        if flow is None or flow.data.get("user_id") != user.id:
            raise AuthError("flow_expired")
        self.accounts.add_credential(user.id, self._verify_registration(credential, flow.challenge, label))
        self.audit.log("passkey.add", True, user.id)

    def _verify_registration(self, credential: dict[str, Any], challenge: bytes, label: str):
        try:
            return self.passkeys.verify_registration(credential, challenge, label)
        except PasskeyError:
            raise AuthError("passkey_failed") from None
