"""Visitor type for the icon and the emergency flag.

Part of the aikos transcriber (split from roomkey tools/talk_identity.py at d0d52b9, code unchanged).
"Who is speaking" logic: the roomkey maintainers have the say here (review required)."""
from __future__ import annotations

import re

from .lexicon import FAMILY_REL, FAMILY_TYPE
from .model import Identity
from .roles import CONTENT_TYPES, URGENT


def classify(ident: Identity, text: str, side: str = "door") -> Identity:
    """Visitor type for the icon and the emergency flag (voice v2, R17.10 / R17.15)."""
    ident.urgent = re.search(URGENT, text, re.I) is not None
    if side == "room":
        ident.vtype = "name" if ident.name else ""
        return ident
    if ident.role == "relation":
        word = ident.speaker.split()[0].lower() if ident.speaker else ""
        ident.vtype = "family" if word in FAMILY_REL else ("kids_friend" if word in ("freund", "freundin", "kumpel")
                                                            and re.search(CONTENT_TYPES[0][1], text, re.I) else "name")
    elif ident.role:
        ident.vtype = ident.role
    elif ident.name:
        ident.vtype = "family" if ident.name.split()[-1].lower() in FAMILY_TYPE else "name"
    else:
        ident.vtype = next((t for t, pat in CONTENT_TYPES if re.search(pat, text, re.I)), "")
    if ident.urgent and ident.vtype in ("", "name", "family", "neighbour"):
        ident.vtype = "emergency" if not ident.vtype else ident.vtype
    return ident
