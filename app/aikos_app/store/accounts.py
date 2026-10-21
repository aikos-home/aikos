"""People, their passkeys, invites and the one-time setup code."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from . import Database, b64d, b64e, new_token, now, token_hash

INVITE_TTL_S = 24 * 3600
SETUP_CODE_TTL_S = 24 * 3600
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


@dataclass(frozen=True)
class User:
    id: int
    handle: bytes
    name: str
    role: str
    ha_person: str
    created_at: int
    disabled: bool


@dataclass(frozen=True)
class Credential:
    id: bytes
    user_id: int
    public_key: bytes
    sign_count: int
    transports: list[str]
    label: str
    created_at: int
    last_used_at: int | None


@dataclass(frozen=True)
class Invite:
    id: int
    name: str
    role: str
    ha_person: str
    user_id: int | None
    """Set when the invite adds a passkey to an existing person (new device, lost phone)."""
    expires_at: int


def _user(row) -> User:
    return User(row["id"], b64d(row["handle"]), row["name"], row["role"], row["ha_person"], row["created_at"],
                row["disabled_at"] is not None)


def _credential(row) -> Credential:
    return Credential(b64d(row["id"]), row["user_id"], b64d(row["public_key"]), row["sign_count"],
                      [t for t in row["transports"].split(",") if t], row["label"], row["created_at"],
                      row["last_used_at"])


def _invite(row) -> Invite:
    return Invite(row["id"], row["name"], row["role"], row["ha_person"], row["user_id"], row["expires_at"])


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _insert_credential(user_ref: str, cred: Credential, user_arg) -> tuple[str, tuple]:
    return (f"INSERT INTO credentials(id, user_id, public_key, sign_count, transports, label, created_at)"
            f" VALUES (?, {user_ref}, ?, ?, ?, ?, ?)",
            (b64e(cred.id), user_arg, b64e(cred.public_key), cred.sign_count, ",".join(cred.transports), cred.label,
             now()))


class Accounts:
    def __init__(self, db: Database) -> None:
        self.db = db

    # people
    def count_users(self) -> int:
        return self.db.one("SELECT COUNT(*) AS n FROM users WHERE disabled_at IS NULL")["n"]

    def get_user(self, user_id: int) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        return _user(row) if row else None

    def user_by_handle(self, handle: bytes) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE handle = ?", (b64e(handle),))
        return _user(row) if row else None

    def list_users(self) -> list[User]:
        return [_user(r) for r in self.db.query("SELECT * FROM users ORDER BY id")]

    def disable_user(self, user_id: int) -> None:
        self.db.batch([("UPDATE users SET disabled_at = ? WHERE id = ? AND disabled_at IS NULL", (now(), user_id)),
                       ("DELETE FROM sessions WHERE user_id = ?", (user_id,))])

    @staticmethod
    def new_handle() -> bytes:
        """The WebAuthn user handle: random, never the database id (it is stored on the authenticator)."""
        return secrets.token_bytes(32)

    def create_user_with_credential(self, handle: bytes, name: str, role: str, ha_person: str, cred: Credential) -> User:
        h = b64e(handle)
        self.db.batch([
            ("INSERT INTO users(handle, name, role, ha_person, created_at) VALUES (?, ?, ?, ?, ?)",
             (h, name, role, ha_person, now())),
            _insert_credential("(SELECT id FROM users WHERE handle = ?)", cred, h),
        ])
        return self.user_by_handle(handle)

    # passkeys
    def add_credential(self, user_id: int, cred: Credential) -> None:
        self.db.batch([_insert_credential("?", cred, user_id)])

    def credential(self, cred_id: bytes) -> Credential | None:
        row = self.db.one("SELECT * FROM credentials WHERE id = ?", (b64e(cred_id),))
        return _credential(row) if row else None

    def credentials_of(self, user_id: int) -> list[Credential]:
        return [_credential(r) for r in self.db.query(
            "SELECT * FROM credentials WHERE user_id = ? ORDER BY created_at", (user_id,))]

    def touch_credential(self, cred_id: bytes, sign_count: int) -> None:
        self.db.execute("UPDATE credentials SET sign_count = ?, last_used_at = ? WHERE id = ?",
                        (sign_count, now(), b64e(cred_id)))

    def delete_credential(self, user_id: int, cred_id: bytes) -> bool:
        """Removes one of the person's passkeys, but never the last one (the person would be locked out)."""
        return self.db.execute(
            "DELETE FROM credentials WHERE id = ? AND user_id = ?"
            " AND (SELECT COUNT(*) FROM credentials WHERE user_id = ?) > 1",
            (b64e(cred_id), user_id, user_id)).rowcount == 1

    # invites
    def create_invite(self, name: str, role: str, ha_person: str, created_by: int | None,
                      user_id: int | None = None) -> tuple[str, Invite]:
        token = new_token()
        expires = now() + INVITE_TTL_S
        res = self.db.execute("INSERT INTO invites(token_hash, name, role, ha_person, user_id, created_by, created_at,"
                              " expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                              (token_hash(token), name, role, ha_person, user_id, created_by, now(), expires))
        return token, Invite(res.lastrowid, name, role, ha_person, user_id, expires)

    def open_invite(self, token: str) -> Invite | None:
        """An unused, unexpired invite for this token, or None."""
        return self._open_invite("token_hash = ?", token_hash(token))

    def open_invite_by_id(self, invite_id: int) -> Invite | None:
        return self._open_invite("id = ?", invite_id)

    def _open_invite(self, where: str, value) -> Invite | None:
        row = self.db.one(f"SELECT * FROM invites WHERE {where} AND used_at IS NULL AND expires_at > ?", (value, now()))
        return _invite(row) if row else None

    def use_invite(self, invite_id: int) -> bool:
        """Marks the invite used. False if it was used or expired meanwhile (each invite works exactly once)."""
        return self.db.execute("UPDATE invites SET used_at = ? WHERE id = ? AND used_at IS NULL AND expires_at > ?",
                               (now(), invite_id, now())).rowcount == 1

    # setup code (first start only)
    def new_setup_code(self) -> str:
        """A fresh code. Older unused codes stay valid until they expire, so three VMs starting at once each have one
        that works."""
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
        self.db.batch([("DELETE FROM setup_codes WHERE expires_at <= ?", (now(),)),
                       ("INSERT INTO setup_codes(code_hash, created_at, expires_at) VALUES (?, ?, ?)",
                        (token_hash(code), now(), now() + SETUP_CODE_TTL_S))])
        return "-".join(code[i:i + 4] for i in range(0, 12, 4))

    def setup_code_valid(self, code: str) -> bool:
        return self.db.one("SELECT 1 AS ok FROM setup_codes WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
                           (token_hash(normalize_code(code)), now())) is not None

    def use_setup_code(self, code: str) -> bool:
        """Uses this code and voids every other open one: the first person exists now."""
        res = self.db.execute("UPDATE setup_codes SET used_at = ? WHERE code_hash = ? AND used_at IS NULL"
                              " AND expires_at > ?", (now(), token_hash(normalize_code(code)), now()))
        if res.rowcount != 1:
            return False
        self.db.execute("UPDATE setup_codes SET used_at = ? WHERE used_at IS NULL", (now(),))
        return True
