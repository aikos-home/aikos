"""Rule A8 (fixed roles, matrix 2.4a) and A15 (a message for X: only X and the superadmin)."""

from aikos_app.roles import Cap, Role, can, may_see_message

EXPECTED = {
    Role.SUPERADMIN: set(Cap),
    Role.ADULT: {Cap.MESSAGES_OWN, Cap.DRAWINGS, Cap.DOOR_ACT, Cap.ROOMKEY_ANNOUNCE, Cap.BELL_SETTINGS, Cap.LOGS,
                 Cap.ROOMKEY_OWN_ROOM},
    Role.CHILD: {Cap.MESSAGES_OWN, Cap.ROOMKEY_OWN_ROOM},
}


def test_matrix_is_exactly_2_4a():
    for role, caps in EXPECTED.items():
        for cap in Cap:
            assert can(role, cap) == (cap in caps), (role, cap)


def test_only_superadmin_manages_people_and_sees_all_messages():
    assert [r for r in Role if can(r, Cap.PEOPLE_MANAGE)] == [Role.SUPERADMIN]
    assert [r for r in Role if can(r, Cap.MESSAGES_ALL)] == [Role.SUPERADMIN]


def test_message_for_a_person_is_seen_by_that_person_and_superadmin_only():
    assert may_see_message(Role.SUPERADMIN, ["Alex"], "Sam")
    assert may_see_message(Role.ADULT, ["Sam"], "Sam")
    assert may_see_message(Role.ADULT, ["sam "], "Sam")
    assert not may_see_message(Role.ADULT, ["Robin"], "Sam")
    assert not may_see_message(Role.CHILD, ["Robin"], "Sam")
    assert may_see_message(Role.CHILD, ["Robin"], "Robin")


def test_message_for_everyone():
    assert may_see_message(Role.ADULT, ["Sam"], "")
    assert may_see_message(Role.SUPERADMIN, ["Alex"], "")
    assert not may_see_message(Role.CHILD, ["Robin"], "")  # open question (feature file §7); narrowest until then


def test_empty_names_never_match():
    assert not may_see_message(Role.ADULT, ["", "  "], "Sam")
