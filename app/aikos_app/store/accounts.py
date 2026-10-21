"""People, their passkeys, invites and the one-time setup code."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from . import Database, new_token, now, token_hash

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
    return User(row["id"], row["handle"], row["name"], row["role"], row["ha_person"], row["created_at"],
                row["disabled_at"] is not None)


def _credential(row) -> Credential:
    return Credential(row["id"], row["user_id"], row["public_key"], row["sign_count"],
                      [t for t in row["transports"].split(",") if t], row["label"], row["created_at"],
                      row["last_used_at"])


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


class Accounts:
    def __init__(self, db: Database) -> None:
        self.db = db

    # people
    def count_users(self) -> int:
        return self.db.one("SELECT COUNT(*) FROM users WHERE disabled_at IS NULL")[0]

    def get_user(self, user_id: int) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        return _user(row) if row else None

    def user_by_handle(self, handle: bytes) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE handle = ?", (handle,))
        return _user(row) if row else None

    def list_users(self) -> list[User]:
        return [_user(r) for r in self.db.query("SELECT * FROM users ORDER BY id")]

    def disable_user(self, user_id: int) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE users SET disabled_at = ? WHERE id = ? AND disabled_at IS NULL", (now(), user_id))
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    @staticmethod
    def new_handle() -> bytes:
        """The WebAuthn user handle: random, never the database id (it is stored on the authenticator)."""
        return secrets.token_bytes(32)

    def create_user_with_credential(self, handle: bytes, name: str, role: str, ha_person: str, cred: Credential) -> User:
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO users(handle, name, role, ha_person, created_at) VALUES (?,?,?,?,?)",
                            (handle, name, role, ha_person, now()))
            user_id = cur.lastrowid
            self._insert_credential(c, user_id, cred)
        return self.get_user(user_id)

    # passkeys
    @staticmethod
    def _insert_credential(c, user_id: int, cred: Credential) -> None:
        c.execute("INSERT INTO credentials(id, user_id, public_key, sign_count, transports, label, created_at)"
                  " VALUES (?,?,?,?,?,?,?)",
                  (cred.id, user_id, cred.public_key, cred.sign_count, ",".join(cred.transports), cred.label, now()))

    def add_credential(self, user_id: int, cred: Credential) -> None:
        with self.db.tx() as c:
            self._insert_credential(c, user_id, cred)

    def credential(self, cred_id: bytes) -> Credential | None:
        row = self.db.one("SELECT * FROM credentials WHERE id = ?", (cred_id,))
        return _credential(row) if row else None

    def credentials_of(self, user_id: int) -> list[Credential]:
        return [_credential(r) for r in self.db.query(
            "SELECT * FROM credentials WHERE user_id = ? ORDER BY created_at", (user_id,))]

    def touch_credential(self, cred_id: bytes, sign_count: int) -> None:
        self.db.execute("UPDATE credentials SET sign_count = ?, last_used_at = ? WHERE id = ?",
                        (sign_count, now(), cred_id))

    def delete_credential(self, user_id: int, cred_id: bytes) -> bool:
        """Removes one of the person's passkeys, but never the last one (the person would be locked out)."""
        with self.db.tx() as c:
            n = c.execute("SELECT COUNT(*) FROM credentials WHERE user_id = ?", (user_id,)).fetchone()[0]
            if n <= 1:
                return False
            return c.execute("DELETE FROM credentials WHERE id = ? AND user_id = ?", (cred_id, user_id)).rowcount == 1

    # invites
    def create_invite(self, name: str, role: str, ha_person: str, created_by: int | None,
                      user_id: int | None = None) -> tuple[str, Invite]:
        token = new_token()
        expires = now() + INVITE_TTL_S
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO invites(token_hash, name, role, ha_person, user_id, created_by, created_at,"
                            " expires_at) VALUES (?,?,?,?,?,?,?,?)",
                            (token_hash(token), name, role, ha_person, user_id, created_by, now(), expires))
        return token, Invite(cur.lastrowid, name, role, ha_person, user_id, expires)

    def open_invite(self, token: str) -> Invite | None:
        """An unused, unexpired invite for this token, or None."""
        return self._open_invite("token_hash = ?", token_hash(token))

    def open_invite_by_id(self, invite_id: int) -> Invite | None:
        return self._open_invite("id = ?", invite_id)

    def _open_invite(self, where: str, value) -> Invite | None:
        row = self.db.one(f"SELECT * FROM invites WHERE {where} AND used_at IS NULL AND expires_at > ?", (value, now()))
        return Invite(row["id"], row["name"], row["role"], row["ha_person"], row["user_id"],
                      row["expires_at"]) if row else None

    def use_invite(self, invite_id: int) -> bool:
        """Marks the invite used. False if it was used or expired meanwhile (each invite works exactly once)."""
        cur = self.db.execute("UPDATE invites SET used_at = ? WHERE id = ? AND used_at IS NULL AND expires_at > ?",
                              (now(), invite_id, now()))
        return cur.rowcount == 1

    # setup code (first start only)
    def new_setup_code(self) -> str:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
        with self.db.tx() as c:
            c.execute("DELETE FROM setup_codes WHERE used_at IS NULL")
            c.execute("INSERT INTO setup_codes(code_hash, created_at, expires_at) VALUES (?,?,?)",
                      (token_hash(code), now(), now() + SETUP_CODE_TTL_S))
        return "-".join(code[i:i + 4] for i in range(0, 12, 4))

    def setup_code_valid(self, code: str) -> bool:
        return self.db.one("SELECT 1 FROM setup_codes WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
                           (token_hash(normalize_code(code)), now())) is not None

    def use_setup_code(self, code: str) -> bool:
        cur = self.db.execute("UPDATE setup_codes SET used_at = ? WHERE code_hash = ? AND used_at IS NULL"
                              " AND expires_at > ?", (now(), token_hash(normalize_code(code)), now()))
        return cur.rowcount == 1
