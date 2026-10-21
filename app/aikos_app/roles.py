"""Fixed roles and what each may do (feature file aikos-app, rule A8, matrix 2.4a).

Roles are fixed in code; an account only carries one. Resource rules (whose message, whose room) sit next to them here so
every endpoint asks the same functions.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SUPERADMIN = "superadmin"
    ADULT = "adult"
    CHILD = "child"


class Cap(StrEnum):
    MESSAGES_OWN = "messages.own"
    """Hear, answer live and delete messages for oneself and for everyone."""
    MESSAGES_ALL = "messages.all"
    """See messages addressed to anybody (rule A15: the superadmin)."""
    DRAWINGS = "drawings"
    DOOR_ACT = "door.act"
    """Text, picture, greeting to the door; talk to the door."""
    ROOMKEY_ANNOUNCE = "roomkey.announce"
    BELL_SETTINGS = "bell.settings"
    """Mute the bell, quiet hours."""
    LOGS = "logs"
    """Call and radar history."""
    ROOMKEY_OWN_ROOM = "roomkey.own_room"
    ROOMKEY_ALL = "roomkey.all"
    PEOPLE_MANAGE = "people.manage"
    """Invite people, assign roles, block devices."""


ROLE_CAPS: dict[Role, frozenset[Cap]] = {
    Role.SUPERADMIN: frozenset(Cap),
    Role.ADULT: frozenset({
        Cap.MESSAGES_OWN, Cap.DRAWINGS, Cap.DOOR_ACT, Cap.ROOMKEY_ANNOUNCE, Cap.BELL_SETTINGS, Cap.LOGS,
        Cap.ROOMKEY_OWN_ROOM,
    }),
    # Children get accounts later (A22). What they see of messages "for everyone" and drawings is still open (feature
    # file §7), so they get the narrowest set until the owner decides.
    Role.CHILD: frozenset({Cap.MESSAGES_OWN, Cap.ROOMKEY_OWN_ROOM}),
}

CHILD_SEES_MESSAGES_FOR_EVERYONE = False


def can(role: Role | str, cap: Cap) -> bool:
    return cap in ROLE_CAPS.get(Role(role), frozenset())


def capabilities(role: Role | str) -> list[str]:
    return sorted(c.value for c in ROLE_CAPS.get(Role(role), frozenset()))


def _same_name(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def may_see_message(role: Role | str, own_names: list[str], recipient: str) -> bool:
    """Rule A15: a message for X is visible to X and the superadmin; a message for everyone to every resident.

    `own_names` are the names the person is known by at the door (account name, Home Assistant person name).
    """
    role = Role(role)
    if can(role, Cap.MESSAGES_ALL):
        return True
    if not can(role, Cap.MESSAGES_OWN):
        return False
    if not recipient.strip():
        return role != Role.CHILD or CHILD_SEES_MESSAGES_FOR_EVERYONE
    return any(_same_name(recipient, n) for n in own_names if n)
