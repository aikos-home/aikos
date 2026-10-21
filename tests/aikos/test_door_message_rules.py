"""The door message register's rules without Home Assistant (aikos-app A10, A15, A27, A38)."""
from datetime import datetime, timedelta, timezone

from custom_components.aikos.door_messages import Register

T0 = datetime(2026, 10, 21, 8, 47, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def recorded(r: Register, name="nachricht-20261021-084712.mp3", recipient_screen=None, words=(), saved_at=15.0):
    """One message as the door does it: screen names the recipient, recording on, words, off, recorder saves."""
    if recipient_screen is not None:
        r.recipient_chosen(recipient_screen, at(0))
    r.recording(True, at(0.5))
    for t, said, who in words:
        r.words(said, who, at(t))
    r.recording(False, at(10))
    return r.saved(name, 9.4, "", at(saved_at))


def test_a_message_gets_recipient_words_and_speaker():
    r = Register()
    m = recorded(r, recipient_screen="Alex", words=[(3, "Hallo, hier ist die Post.", "Paketdienst"), (6, "Das Paket liegt vor der Tür.", "")])
    assert (m.recipient, m.seconds, m.speaker) == ("Alex", 9.4, "Paketdienst")
    assert m.text == "Hallo, hier ist die Post. Das Paket liegt vor der Tür."
    assert m.id == "nachricht-20261021-084712" and m.time == "2026-10-21T08:47:15+00:00" and m.heard_by == []


def test_late_words_update_the_saved_message_and_count_as_a_change():
    r = Register()
    m = recorded(r, words=[(3, "Hallo.", "")])
    rev = r.revision
    assert r.words("Bis später.", "", at(18)) is True                # after saving, within 30 s of the end
    assert m.text == "Hallo. Bis später." and r.revision == rev + 1
    assert r.words("Bis später.", "", at(19)) is False                # a repeated sentence is no new text
    assert r.words("Zu spät.", "", at(41)) is False                   # more than 30 s after the end
    assert m.text == "Hallo. Bis später."


def test_words_outside_a_recording_are_not_taken():
    r = Register()
    assert r.words("Gespräch, keine Nachricht.", "", at(1)) is False
    m = r.saved("nachricht-20261021-084712.mp3", 3, "", at(5))
    assert m.text == ""


def test_the_screens_recipient_wins_but_only_while_fresh_and_only_once():
    r = Register()
    assert recorded(r, recipient_screen="Alex").recipient == "Alex"
    assert r.saved("nachricht-20261021-090000.mp3", 4, "Kim", at(60)).recipient == "Kim"   # used up: the recorder's value
    r.recipient_chosen("Alex", at(100))
    assert r.saved("nachricht-20261021-091000.mp3", 4, "", at(100 + 301)).recipient == ""   # stale choice
    r.recipient_chosen("Alex", at(500))
    r.failed()                                                                               # recording failed: forget it
    assert r.saved("nachricht-20261021-092000.mp3", 4, "", at(510)).recipient == ""


def test_a_new_recording_does_not_inherit_old_words():
    r = Register()
    recorded(r, words=[(3, "Erste Nachricht.", "")])
    r.recording(True, at(100))
    r.recording(False, at(105))
    m = r.saved("nachricht-20261021-084900.mp3", 5, "", at(110))
    assert m.text == ""


def test_a_save_long_after_the_recording_gets_no_words():
    r = Register()
    r.recording(True, at(0))
    r.words("Hallo.", "", at(2))
    r.recording(False, at(5))
    assert r.saved("nachricht-20261021-085000.mp3", 2, "", at(5 + 121)).text == ""


def test_saved_twice_keeps_the_first_and_bad_names_are_refused():
    r = Register()
    m = recorded(r)
    assert r.saved(m.file, 1.0, "Kim", at(30)) is m and m.seconds == 9.4 and len(r) == 1
    for bad in ("../x.mp3", "a/b.mp3", "x.wav", ".mp3", "", "x..y.mp3", "x" * 130 + ".mp3"):
        assert r.saved(bad, 1, "", at(40)) is None, bad
    assert len(r) == 1


def test_adopt_takes_only_the_recorders_files_once():
    r = Register()
    files = {"nachricht-20261020-101010.mp3": at(-86400), "begruessung.mp3": at(-3600), "nachricht-x/../y.mp3": at(0)}
    assert r.adopt(files) == 1 and r.adopt(files) == 0
    m = r.get("nachricht-20261020-101010")
    assert m.adopted and m.recipient == "" and m.seconds is None and m.time == "2026-10-20T08:47:00+00:00"


def test_heard_once_per_person_and_remove():
    r = Register()
    m = recorded(r)
    assert r.heard(m.id, "Alex") and not r.heard(m.id, "Alex") and r.heard(m.id, "Kim")
    assert m.heard_by == ["Alex", "Kim"]
    assert not r.heard("nope", "Alex") and not r.heard(m.id, "  ")
    assert r.remove(m.id) is m and r.get(m.id) is None and r.remove(m.id) is None


def test_listing_is_newest_first_and_storage_round_trips():
    r = Register()
    recorded(r, name="nachricht-20261021-084712.mp3", recipient_screen="Alex", words=[(2, "Eins.", "Post")])
    r.saved("nachricht-20261021-095000.mp3", 3, "", at(3600))
    r.heard("nachricht-20261021-084712", "Alex")
    assert [m.id for m in r.listing()] == ["nachricht-20261021-095000", "nachricht-20261021-084712"]
    again = Register.from_dict(r.to_dict())
    assert [m.as_dict() for m in again.listing()] == [m.as_dict() for m in r.listing()] and again.revision == r.revision


def test_storage_drops_entries_with_unsafe_or_mismatched_files():
    data = {"revision": 3, "messages": [
        {"id": "ok", "file": "ok.mp3", "time": "2026-10-21T08:00:00+00:00", "seconds": 2, "recipient": "", "future": 1},
        {"id": "../etc", "file": "../etc.mp3", "time": "", "seconds": None, "recipient": ""},
        {"id": "other", "file": "x.mp3", "time": "", "seconds": None, "recipient": ""},
        "nonsense"]}
    r = Register.from_dict(data)
    assert [m.id for m in r.listing()] == ["ok"] and r.revision == 3
