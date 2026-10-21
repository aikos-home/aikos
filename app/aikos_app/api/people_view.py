"""How people and passkeys look in API answers (no handles, no keys, no hashes)."""

from __future__ import annotations

import base64

from ..roles import capabilities
from ..store.accounts import Credential, User


def user_view(user: User) -> dict:
    return {"id": user.id, "name": user.name, "role": user.role, "ha_person": user.ha_person,
            "capabilities": capabilities(user.role)}


def credential_view(cred: Credential) -> dict:
    return {"id": base64.urlsafe_b64encode(cred.id).decode("ascii").rstrip("="), "label": cred.label,
            "created_at": cred.created_at, "last_used_at": cred.last_used_at}


def credential_id(text: str) -> bytes | None:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        return None


def door_names(user: User) -> list[str]:
    """Names the person is known by at the door: account name and the Home Assistant person's object id."""
    names = [user.name]
    if user.ha_person.startswith("person."):
        names.append(user.ha_person.split(".", 1)[1].replace("_", " "))
    return names
