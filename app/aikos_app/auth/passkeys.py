"""WebAuthn ceremonies (py_webauthn). Discoverable credentials (no user name at login), user verification required."""

from __future__ import annotations

from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json_dict, parse_authentication_credential_json
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse, WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..store.accounts import Credential


class PasskeyError(Exception):
    pass


def _transports(names: list[str]) -> list[AuthenticatorTransport]:
    out = []
    for n in names:
        try:
            out.append(AuthenticatorTransport(n))
        except ValueError:
            pass
    return out


class Passkeys:
    def __init__(self, rp_id: str, rp_name: str, origin: str) -> None:
        self.rp_id, self.rp_name, self.origin = rp_id, rp_name, origin

    def registration(self, handle: bytes, name: str, existing: list[Credential]) -> tuple[dict[str, Any], bytes]:
        opts = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=self.rp_name,
            user_id=handle,
            user_name=name,
            user_display_name=name,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=c.id, transports=_transports(c.transports))
                                 for c in existing],
        )
        return options_to_json_dict(opts), opts.challenge

    def verify_registration(self, credential: dict[str, Any], challenge: bytes, label: str = "") -> Credential:
        try:
            v = verify_registration_response(credential=credential, expected_challenge=challenge,
                                             expected_rp_id=self.rp_id, expected_origin=self.origin,
                                             require_user_verification=True)
        except (InvalidRegistrationResponse, WebAuthnException, KeyError, ValueError, TypeError) as e:
            raise PasskeyError(str(e)) from e
        transports = [t for t in (credential.get("response") or {}).get("transports") or [] if isinstance(t, str)]
        return Credential(id=v.credential_id, user_id=0, public_key=v.credential_public_key, sign_count=v.sign_count,
                          transports=transports, label=label[:80], created_at=0, last_used_at=None)

    def authentication(self) -> tuple[dict[str, Any], bytes]:
        opts = generate_authentication_options(rp_id=self.rp_id, user_verification=UserVerificationRequirement.REQUIRED)
        return options_to_json_dict(opts), opts.challenge

    @staticmethod
    def identify(credential: dict[str, Any]) -> tuple[bytes, bytes | None]:
        """Credential id and user handle of a login response, before it is verified."""
        try:
            parsed = parse_authentication_credential_json(credential)
        except (WebAuthnException, KeyError, ValueError, TypeError) as e:
            raise PasskeyError(str(e)) from e
        return parsed.raw_id, parsed.response.user_handle

    def verify_authentication(self, credential: dict[str, Any], challenge: bytes, stored: Credential) -> int:
        """Checks the signature against the stored public key; returns the new signature counter."""
        try:
            v = verify_authentication_response(credential=credential, expected_challenge=challenge,
                                               expected_rp_id=self.rp_id, expected_origin=self.origin,
                                               credential_public_key=stored.public_key,
                                               credential_current_sign_count=stored.sign_count,
                                               require_user_verification=True)
        except (InvalidAuthenticationResponse, WebAuthnException, KeyError, ValueError, TypeError) as e:
            raise PasskeyError(str(e)) from e
        return v.new_sign_count
