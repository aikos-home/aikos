"""The database rules that need atomicity, on SQLite and (with AIKOS_TEST_DB=rqlite://…) on a real rqlite cluster."""

from __future__ import annotations

import sqlite3

import pytest
from conftest import fresh_db

from aikos_app.store import SCHEMA_VERSION, Database, b64e, now, token_hash
from aikos_app.store.accounts import Accounts, Credential
from aikos_app.store.flows import Flows
from aikos_app.store.sessions import Sessions


def cred(n: int) -> Credential:
    return Credential(id=bytes([n]) * 16, user_id=0, public_key=b"\x01pk" + bytes([n]), sign_count=0,
                      transports=["internal"], label="Test", created_at=0, last_used_at=None)


@pytest.fixture
def db(tmp_path):
    d = fresh_db(tmp_path)
    yield d
    d.close()


def test_user_and_first_passkey_together(db):
    acc = Accounts(db)
    user = acc.create_user_with_credential(b"h" * 32, "Alex", "superadmin", "", cred(1))
    assert user.handle == b"h" * 32 and user.name == "Alex"
    stored = acc.credential(cred(1).id)
    assert stored.user_id == user.id and stored.public_key == cred(1).public_key and stored.transports == ["internal"]


def test_a_failing_batch_leaves_nothing(db):
    acc = Accounts(db)
    acc.create_user_with_credential(b"a" * 32, "Alex", "superadmin", "", cred(1))
    with pytest.raises(Exception):
        acc.create_user_with_credential(b"b" * 32, "Sam", "adult", "", cred(1))  # same passkey id: second insert fails
    assert [u.name for u in acc.list_users()] == ["Alex"]


def test_last_passkey_stays(db):
    acc = Accounts(db)
    user = acc.create_user_with_credential(b"a" * 32, "Alex", "superadmin", "", cred(1))
    assert not acc.delete_credential(user.id, cred(1).id)
    acc.add_credential(user.id, cred(2))
    assert acc.delete_credential(user.id, cred(1).id)
    assert not acc.delete_credential(user.id, cred(2).id)


def test_flow_is_taken_once(db):
    flows = Flows(db)
    fid = flows.start("login", b"challenge-bytes", {"x": 1})
    first = flows.take(fid, "login")
    assert first.challenge == b"challenge-bytes" and first.data == {"x": 1}
    assert flows.take(fid, "login") is None
    assert flows.take(flows.start("login", b"c"), "setup") is None


def test_setup_codes_of_several_nodes_all_work_until_one_is_used(db):
    acc = Accounts(db)
    a, b = acc.new_setup_code(), acc.new_setup_code()
    assert acc.setup_code_valid(a) and acc.setup_code_valid(b)
    assert acc.use_setup_code(b)
    assert not acc.setup_code_valid(a) and not acc.use_setup_code(a)


def test_invite_once(db):
    acc = Accounts(db)
    token, inv = acc.create_invite("Sam", "adult", "", None)
    assert acc.open_invite(token).id == inv.id
    assert acc.use_invite(inv.id) and not acc.use_invite(inv.id)
    assert acc.open_invite(token) is None


def test_sessions(db):
    acc, ses = Accounts(db), Sessions(db)
    user = acc.create_user_with_credential(b"a" * 32, "Alex", "superadmin", "", cred(1))
    token = ses.create(user.id, "Phone")
    assert ses.resolve(token).user_id == user.id
    acc.disable_user(user.id)
    assert ses.resolve(token) is None


def test_old_local_file_is_converted(tmp_path):
    """Step 1 wrote BLOBs (schema 1, PRAGMA user_version). Opening it with schema 2 keeps every person and passkey."""
    path = tmp_path / "old.sqlite3"
    c = sqlite3.connect(path)
    c.executescript("""
      CREATE TABLE users(id INTEGER PRIMARY KEY, handle BLOB NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL,
        ha_person TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, disabled_at INTEGER);
      CREATE TABLE credentials(id BLOB PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), public_key BLOB NOT NULL,
        sign_count INTEGER NOT NULL, transports TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL, last_used_at INTEGER);
      CREATE TABLE sessions(token_hash BLOB PRIMARY KEY, user_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '');
      CREATE TABLE flows(id TEXT PRIMARY KEY, kind TEXT NOT NULL, challenge BLOB NOT NULL, data TEXT NOT NULL DEFAULT '{}',
        expires_at INTEGER NOT NULL);
      CREATE TABLE invites(id INTEGER PRIMARY KEY, token_hash BLOB NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL,
        ha_person TEXT NOT NULL DEFAULT '', user_id INTEGER, created_by INTEGER, created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL, used_at INTEGER);
      CREATE TABLE setup_codes(code_hash BLOB PRIMARY KEY, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        used_at INTEGER);
      CREATE TABLE audit(id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, user_id INTEGER, action TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '', ok INTEGER NOT NULL, ip TEXT NOT NULL DEFAULT '');
      PRAGMA user_version = 1;
    """)
    import hashlib
    c.execute("INSERT INTO users VALUES (1, ?, 'Alex', 'superadmin', '', 1, NULL)", (b"H" * 32,))
    c.execute("INSERT INTO credentials VALUES (?, 1, ?, 3, 'internal', 'PC', 1, NULL)", (b"C" * 16, b"PUBKEY"))
    c.execute("INSERT INTO sessions VALUES (?, 1, 1, ?, ?, '')",
              (hashlib.sha256(b"old-session").digest(), now() + 999, now()))
    c.commit()
    c.close()

    db = Database(path)
    acc = Accounts(db)
    assert acc.user_by_handle(b"H" * 32).name == "Alex"
    assert acc.credential(b"C" * 16).public_key == b"PUBKEY"
    assert Sessions(db).resolve("old-session").user_id == 1
    assert db.one("SELECT value FROM meta WHERE key = 'schema'")["value"] == str(SCHEMA_VERSION)
    assert token_hash("old-session") == b64e(hashlib.sha256(b"old-session").digest())
    db.close()
    Database(path).close()  # opening again is a no-op


def test_a_new_device_link_voids_the_older_ones(db):
    acc = Accounts(db)
    user = acc.create_user_with_credential(b"a" * 32, "Alex", "superadmin", "", cred(1))
    first, _ = acc.create_invite(user.name, user.role, "", user.id, user_id=user.id)
    second, _ = acc.create_invite(user.name, user.role, "", user.id, user_id=user.id)
    other, _ = acc.create_invite("Sam", "adult", "", user.id)
    assert acc.open_invite(first) is None and acc.open_invite(second) is not None
    assert acc.open_invite(other) is not None  # invites for new people are not touched


def test_a_compatible_newer_schema_still_opens_for_a_rollback(db):
    """A rolling update migrates the shared database first; if the new image fails, the previous one must still start.
    Additive changes keep `schema_min`, so the older app opens the newer database and leaves it as it is."""
    from aikos_app.store import SCHEMA_MIN, DatabaseError
    assert db.one("SELECT value FROM meta WHERE key = 'schema_min'")["value"] == "2"
    try:
        db.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION + 1),))
        Database(db.backend)
        assert db.one("SELECT value FROM meta WHERE key = 'schema'")["value"] == str(SCHEMA_VERSION + 1)  # not stepped back
        db.execute("UPDATE meta SET value = ? WHERE key = 'schema_min'", (str(SCHEMA_VERSION + 1),))
        with pytest.raises(DatabaseError, match="newer"):
            Database(db.backend)
    finally:  # the rqlite test database is shared: leave it as the next test expects it
        db.batch([("UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION),)),
                  ("UPDATE meta SET value = ? WHERE key = 'schema_min'", (str(SCHEMA_MIN),))])
