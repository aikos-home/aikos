"""Call-log rules without Home Assistant: the cases of homeassistant/tests/test_call_log.py (R22, R25, R26, R27)."""
import json

from custom_components.aikos.call_log import FEED, KEEP, CallLog

DOOR = {"text": "Guten Tag, Paketdienst von DHL, ich habe ein Paket.", "message": "Ich habe ein Paket.",
        "speaker": "Paketdienst · DHL", "speaker_role": "parcel", "urgent": False, "language": "de"}


def started():
    log = CallLog()
    log.start("2026-10-02T12:00:00+00:00")
    return log


def test_door_and_room_in_order_with_role_and_last_id():
    log = started()
    log.add("door", "t1", DOOR)
    log.add("room", "t9", {"text": "Hier ist Alex, ich komme gleich.", "message": "Ich komme gleich.", "speaker": "Alex",
                            "speaker_role": "name", "language": "de", "device": "aikos RoomKey Test"})
    assert [m["side"] for m in log.messages] == ["door", "room"]
    assert (log.messages[0]["who"], log.messages[0]["role"], log.messages[0]["text"]) == ("Paketdienst · DHL", "parcel", "Ich habe ein Paket.")
    assert log.last_id == "room-t9"
    shown = json.loads(log.feed_json())
    assert [m["id"] for m in shown] == ["door-t1", "room-t9"]
    assert all({"id", "side", "who", "text"} <= set(m) for m in shown)       # the screens' contract


def test_a_later_update_replaces_the_message():
    log = started()
    log.add("door", "t1", DOOR)
    log.add("door", "t1", dict(DOOR, language="en", language_name="Englisch"))
    assert len(log.messages) == 1 and log.messages[0]["lang"] == "Englisch"


def test_r25_visitor_identity_sticks_with_own_role_and_urgency():
    log = started()
    log.add("door", "t1", DOOR)
    log.add("door", "t2", dict(DOOR, text="Hilfe, ein Unfall!", message="Hilfe, ein Unfall!", speaker="", speaker_role="emergency", urgent=True))
    m = log.messages[-1]
    assert (m["who"], m["role"], m["urgent"], m["sticky"]) == ("Paketdienst · DHL", "emergency", True, True)


def test_r26_resident_name_sticks_to_its_key_only():
    log = started()
    log.add("room", "t1", {"text": "Hier ist Alex.", "speaker": "Alex", "speaker_role": "name", "device": "Key A"})
    log.add("room", "t2", {"text": "Ich komme.", "speaker": "", "device": "Key A"})
    log.add("room", "t3", {"text": "Wer ist da?", "speaker": "", "device": "Key B"})
    assert (log.messages[1]["who"], log.messages[1]["sticky"]) == ("Alex", True)
    assert (log.messages[2]["who"], log.messages[2]["sticky"]) == ("Key B", False)


def test_new_call_inherits_nothing():
    log = started()
    log.add("door", "t1", DOOR)
    log.end()
    log.start("2026-10-02T12:05:00+00:00")
    log.add("door", "t5", dict(DOOR, speaker="", speaker_role="", text="Hallo?", message="Hallo?"))
    assert (log.messages[0]["who"], log.messages[0]["sticky"]) == ("Besucher", False)


def test_r27_feed_is_the_newest_10_oldest_first_and_log_keeps_20():
    log = started()
    for k in range(12):
        log.add("door", f"t{k:02d}", dict(DOOR, speaker="", text=f"Satz {k}.", message=f"Satz {k}."))
    feed = json.loads(log.feed_json())
    assert len(log.messages) == 12 and len(feed) == FEED
    assert (feed[0]["text"], feed[-1]["text"]) == ("Satz 2.", "Satz 11.")
    for k in range(12, 30):
        log.add("door", f"t{k:02d}", dict(DOOR, text=f"Satz {k}."))
    assert len(log.messages) == KEEP


def test_r22_end_empties_and_keeps_the_call_id():
    log = started()
    log.add("door", "t1", DOOR)
    log.end()
    assert log.messages == [] and log.call_id == "2026-10-02T12:00:00+00:00" and log.feed_json() == "[]"


def test_invalid_transcript_and_text_cut():
    log = started()
    assert not log.add("door", "unavailable", DOOR)
    log.add("door", "t1", dict(DOOR, message="x" * 400))
    assert len(log.messages[0]["text"]) == 300


def test_urgent_as_text_and_room_without_device():
    log = started()
    log.add("door", "t1", dict(DOOR, urgent="false"))
    log.add("room", "t2", {"text": "Ja?", "urgent": "True"})
    assert log.messages[0]["urgent"] is False and log.messages[1]["urgent"] is True
    assert log.messages[1]["who"] == "Bewohner"
