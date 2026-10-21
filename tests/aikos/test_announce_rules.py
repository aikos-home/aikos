"""The rules of the door announcements (sprachausgabe S3, S10–S14): the level decides what may be told, the code picks the
residents' own sentence, places only for residents who agreed and released zones, unknown is never "away"."""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.aikos.announce_rules import (
    AWAY,
    PARCEL,
    QUIET,
    Announcements,
    Resident,
    may_repeat,
    pick,
    sentence,
    where,
)

TEXTS = {PARCEL: "Bitte vor die Tür legen.", AWAY: "Wir sind gerade nicht zu Hause.", QUIET: "Wir können gerade nicht."}
AWAY_BOTH = [Resident("Alex", "Laden", "beim Laden"), Resident("Sam", "not_home")]
HOME = [Resident("Alex", "home"), Resident("Sam", "not_home")]


def ann(level, **kw):
    return Announcements(disclosure=level, voice="v1", texts=dict(TEXTS), **kw)


def test_level_0_tells_nothing_in_any_situation():
    a = ann(0, away_places="Wir sind unterwegs. {wo}.")
    for parcel, muted, residents in ((True, False, HOME), (False, False, AWAY_BOTH), (False, True, HOME)):
        assert pick(a, parcel=parcel, muted=muted, residents=residents) is None


def test_level_1_says_the_away_sentence_never_a_place():
    a = ann(1, away_places="Wir sind unterwegs. {wo}.")
    assert pick(a, parcel=False, muted=False, residents=AWAY_BOTH) == (AWAY, "Wir sind gerade nicht zu Hause.")


def test_level_4_names_only_residents_with_a_released_place():
    a = ann(4, away_places="Wir sind unterwegs. {wo}.")
    residents = [Resident("Alex", "Laden", "beim Laden"), Resident("Sam", "Studio", "")]   # Sam: not agreed / not released
    assert pick(a, parcel=False, muted=False, residents=residents) == (AWAY, "Wir sind unterwegs. Alex ist beim Laden.")


def test_level_4_without_any_place_falls_back_to_the_away_sentence():
    a = ann(4, away_places="Wir sind unterwegs. {wo}.")
    residents = [Resident("Alex", "not_home"), Resident("Sam", "not_home")]
    assert pick(a, parcel=False, muted=False, residents=residents) == (AWAY, "Wir sind gerade nicht zu Hause.")


def test_where_joins_the_places_in_german():
    rs = [Resident("A", "x", "beim Laden"), Resident("B", "y", "im Studio"), Resident("C", "z", "auf der Arbeit")]
    assert where(rs) == "A ist beim Laden, B ist im Studio und C ist auf der Arbeit"
    assert where([Resident("A", "home", "zu Hause")]) == ""            # at home is never a place to tell


def test_an_unknown_resident_is_not_away():
    a = ann(1)
    residents = [Resident("Alex", "not_home"), Resident("Sam", "unknown")]
    assert pick(a, parcel=False, muted=False, residents=residents) is None
    assert pick(a, parcel=False, muted=False, residents=[]) is None   # no residents configured: never "away"


def test_parcel_first_then_away_then_quiet_and_an_empty_sentence_passes_on():
    a = ann(1)
    assert pick(a, parcel=True, muted=True, residents=AWAY_BOTH)[0] == PARCEL
    assert pick(a, parcel=False, muted=True, residents=AWAY_BOTH)[0] == AWAY
    assert pick(a, parcel=False, muted=True, residents=HOME) == (QUIET, "Wir können gerade nicht.")
    a.texts.pop(PARCEL)
    assert pick(a, parcel=True, muted=False, residents=AWAY_BOTH)[0] == AWAY
    assert pick(a, parcel=True, muted=False, residents=HOME) is None   # parcel without a sentence, nothing else applies


def test_sentence_is_the_one_that_would_be_said_now():
    a = ann(4, away_places="Unterwegs: {wo}.")
    assert sentence(a, AWAY, AWAY_BOTH) == "Unterwegs: Alex ist beim Laden."
    assert sentence(a, QUIET, AWAY_BOTH) == "Wir können gerade nicht."
    assert sentence(ann(0), PARCEL, HOME) == ""


@pytest.mark.parametrize("bad", [
    {"disclosure": 5}, {"disclosure": -1}, {"away_places": "Wir sind unterwegs."}, {"texts": {AWAY: "Hier {wo}"}},
])
def test_check_refuses(bad):
    a = Announcements(**{"texts": {}, **bad})
    with pytest.raises(ValueError):
        a.check()


def test_from_dict_keeps_good_data_and_drops_bad():
    a = ann(4, away_places="Unterwegs: {wo}.", places={"zone.aikos_test_laden": "beim Laden"}, named=["person.a"])
    assert Announcements.from_dict(a.to_dict()) == a
    assert Announcements.from_dict({"disclosure": 9}) == Announcements()
    assert Announcements.from_dict({"texts": "nope"}) == Announcements()
    assert Announcements.from_dict(None) == Announcements()
    assert Announcements.from_dict({"texts": {"garden": "x", AWAY: "  Weg   hier "}}).texts == {AWAY: "Weg hier"}


def test_a_second_ring_within_a_minute_gets_no_second_announcement():
    t = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    assert may_repeat(None, t)
    assert not may_repeat(t, t + timedelta(seconds=59))
    assert may_repeat(t, t + timedelta(seconds=60))
