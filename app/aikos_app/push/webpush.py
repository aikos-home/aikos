"""Web Push without a third-party library: message encryption (RFC 8291 with aes128gcm, RFC 8188) and VAPID (RFC 8292).

The push service of the phone's maker (Google, Apple, Mozilla) only carries the encrypted message; it can read neither
text nor anything else (rule G5: and there is never sound in it). Uses `cryptography`, already here for passkeys.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

RECORD_SIZE = 4096
MAX_PLAINTEXT = RECORD_SIZE - 86 - 17  # one record: header (salt, rs, key) and tag + padding delimiter
VAPID_TTL_S = 12 * 3600                # RFC 8292: at most 24 h


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def valid_subscription_keys(p256dh: str, auth: str) -> bool:
    try:
        point, secret = unb64u(p256dh), unb64u(auth)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except (ValueError, TypeError):
        return False
    return len(point) == 65 and len(secret) == 16


def encrypt(plaintext: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            sender_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """The request body for one push (Content-Encoding: aes128gcm). `salt` and `sender_key` only for the RFC's test vector."""
    if len(plaintext) > MAX_PLAINTEXT:
        raise ValueError("push message too long")
    ua_public, auth_secret = unb64u(p256dh), unb64u(auth)
    salt = salt or os.urandom(16)
    sender_key = sender_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(sender_key)
    shared = sender_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # 0x02: the last (and only) record
    return salt + struct.pack("!L", RECORD_SIZE) + bytes([len(as_public)]) + as_public + record


# VAPID: the app identifies itself to the push service with its own key pair
def new_vapid_key() -> str:
    """A new private key, as base64url of its 32-byte scalar."""
    return b64u(ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value.to_bytes(32, "big"))


def _vapid_private(private: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(unb64u(private), "big"), ec.SECP256R1())


def vapid_public(private: str) -> str:
    """The `applicationServerKey` the phone subscribes with."""
    return b64u(_public_bytes(_vapid_private(private)))


def vapid_authorization(endpoint: str, private: str, subject: str, now: float | None = None) -> str:
    u = urlsplit(endpoint)
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(now or time.time()) + VAPID_TTL_S,
                              "sub": subject}, separators=(",", ":")).encode())
    r, s = decode_dss_signature(_vapid_private(private).sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"vapid t={head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={vapid_public(private)}"
