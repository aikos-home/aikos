"""A software passkey for tests: makes WebAuthn registration and login responses like a phone would (ES256, "none")."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from dataclasses import dataclass

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class _Key:
    cred_id: bytes
    private: ec.EllipticCurvePrivateKey
    user_handle: bytes
    rp_id: str
    count: int = 0


class SoftAuthenticator:
    def __init__(self, origin: str, user_verified: bool = True, counter: bool = True) -> None:
        self.origin, self.user_verified, self.counter = origin, user_verified, counter
        self.keys: list[_Key] = []

    def _flags(self, attested: bool) -> int:
        return 0x01 | (0x04 if self.user_verified else 0) | (0x40 if attested else 0)

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin or self.origin,
                           "crossOrigin": False}).encode()

    def create(self, options: dict, origin: str | None = None) -> dict:
        rp_id = options["rp"]["id"]
        key = _Key(os.urandom(16), ec.generate_private_key(ec.SECP256R1()), unb64(options["user"]["id"]), rp_id)
        self.keys.append(key)
        nums = key.private.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        auth_data = (hashlib.sha256(rp_id.encode()).digest() + bytes([self._flags(True)]) + struct.pack(">I", 0)
                     + b"\0" * 16 + struct.pack(">H", len(key.cred_id)) + key.cred_id + cose)
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cdj = self._client_data("webauthn.create", options["challenge"], origin)
        return {"id": b64(key.cred_id), "rawId": b64(key.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cdj), "attestationObject": b64(att), "transports": ["internal"]},
                "clientExtensionResults": {}, "authenticatorAttachment": "platform"}

    def get(self, options: dict, key_index: int = -1, origin: str | None = None) -> dict:
        key = self.keys[key_index]
        if self.counter:
            key.count += 1
        auth_data = hashlib.sha256(key.rp_id.encode()).digest() + bytes([self._flags(False)]) + struct.pack(">I", key.count)
        cdj = self._client_data("webauthn.get", options["challenge"], origin)
        sig = key.private.sign(auth_data + hashlib.sha256(cdj).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(key.cred_id), "rawId": b64(key.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cdj), "authenticatorData": b64(auth_data), "signature": b64(sig),
                             "userHandle": b64(key.user_handle)},
                "clientExtensionResults": {}, "authenticatorAttachment": "platform"}
