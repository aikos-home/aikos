"""Acceptance test of the aikos call log against a running Home Assistant.

Uses only test entities (sensor.talk_transcript_test, sensor.talk_transcript_door_test, input_boolean.aikos_test_in_call,
sensor.aikos_call_log_test) and checks that the live log does not move. Also checks the fields the devices read
(messages_json: id, side, who, text; sensor.aikos_people keys_json: host, name); reading sensor.aikos_people writes nothing.

    AIKOS_HA_URL=http://<ha-host>:8123 AIKOS_HA_TOKEN_FILE=<token file> python homeassistant/tests/test_call_log.py

Exit code 1 if a check fails.
"""
import datetime
import json
import os
import sys
import time
import urllib.request

URL = os.environ["AIKOS_HA_URL"].rstrip("/") + "/api"
TOKEN = open(os.environ["AIKOS_HA_TOKEN_FILE"], encoding="utf-8").read().strip()
WAIT = 2.0
failures = 0


def call(path, body=None, method="GET"):
    req = urllib.request.Request(URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=30).read()
    return json.loads(raw) if raw else None


def check(condition, label):
    global failures
    print(("PASS " if condition else "FAIL ") + label)
    failures += 0 if condition else 1


def test_log():
    return call("/states/sensor.aikos_call_log_test")["attributes"]


def transcript(entity, when, **attributes):
    attributes.setdefault("source", "aikos-test")
    call("/states/" + entity, {"state": when, "attributes": attributes}, "POST")
    time.sleep(WAIT)


def test_call(on):
    call("/services/input_boolean/turn_" + ("on" if on else "off"), {"entity_id": "input_boolean.aikos_test_in_call"}, "POST")
    time.sleep(WAIT)


def new_test_call():
    test_call(False)
    test_call(True)


def people_contract():
    """Contract for the door (talk computer, door screen): keys_json maps each key to at least host and name."""
    try:
        keys = json.loads(call("/states/sensor.aikos_people")["attributes"].get("keys_json") or "{}")
    except Exception as exc:  # no sensor.aikos_people (aikos_local.yaml missing) or not JSON
        check(False, f"sensor.aikos_people readable with keys_json ({exc})")
        return
    check(bool(keys) and all({"host", "name"} <= set(v) for v in keys.values()),
          "people contract: keys_json maps every key to host and name")


def main():
    people_contract()
    live_before = call("/states/sensor.aikos_call_log")
    new_test_call()
    log = test_log()
    check(not log.get("messages") and log.get("call_id"), "a new test call starts empty and has a call_id")
    call_id = log.get("call_id")

    # Timestamps unique per run: HA fires no trigger if a sensor gets the same state and attributes again.
    base = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    stamp = lambda s: (base + datetime.timedelta(seconds=s)).isoformat()
    t_door, t_room, t_urgent = stamp(1), stamp(9), stamp(20)
    door = dict(text="Guten Tag, Paketdienst von DHL, ich habe ein Paket.", message="Ich habe ein Paket.",
                speaker="Paketdienst · DHL", speaker_role="parcel", urgent=False, language="de")
    transcript("sensor.talk_transcript_door_test", t_door, **door)
    transcript("sensor.talk_transcript_test", t_room, text="Hier ist Alex, ich komme gleich.", message="Ich komme gleich.",
               speaker="Alex", speaker_role="name", urgent=False, language="de", device="aikos RoomKey Test")
    log = test_log()
    msgs = log.get("messages") or []
    check([m["side"] for m in msgs] == ["door", "room"], "door and room message in order")
    check(msgs and msgs[0]["who"] == "Paketdienst · DHL" and msgs[0]["role"] == "parcel", "door message: who and role id")
    check(log.get("call_id") == call_id, "call_id stays during the call")
    check(log.get("last_id") == "room-" + t_room, "last_id points to the newest message")
    shown = json.loads(log["messages_json"]) if isinstance(log.get("messages_json"), str) else []
    check(len(shown) == 2 and [m.get("id") for m in shown] == [m.get("id") for m in msgs],
          "messages_json is JSON text with the same messages")
    # Contract for the screens (door screen 0.7.0 reads exactly these): change only via the change path (qualitaet.md §3)
    check(all({"id", "side", "who", "text"} <= set(m) and m["side"] in ("door", "room") for m in shown),
          "screen contract: every message in messages_json has id, side (door/room), who, text")

    transcript("sensor.talk_transcript_door_test", t_door, **dict(door, language="en", language_name="Englisch"))
    msgs = test_log().get("messages") or []
    check(len(msgs) == 2 and msgs[0]["lang"] == "Englisch", "a later update replaces the message (no duplicate)")

    transcript("sensor.talk_transcript_door_test", t_urgent,
               **dict(door, text="Hilfe, ein Unfall!", message="Hilfe, ein Unfall!", speaker="",
                      speaker_role="emergency", urgent=True))
    msgs = test_log().get("messages") or []
    check(len(msgs) == 3 and msgs[-1]["urgent"] is True and msgs[-1]["who"] == "Paketdienst · DHL" and msgs[-1].get("sticky") is True
          and msgs[-1]["role"] == "emergency",
          "R25: a later door message without a speaker keeps the visitor's identity (sticky), own role and urgency")
    t_room2, t_other = stamp(24), stamp(26)
    transcript("sensor.talk_transcript_test", t_room2, text="Ich komme.", message="Ich komme.", speaker="", speaker_role="",
               urgent=False, language="de", device="aikos RoomKey Test")
    transcript("sensor.talk_transcript_test", t_other, text="Wer ist da?", message="Wer ist da?", speaker="", speaker_role="",
               urgent=False, language="de", device="aikos RoomKey Test 2")
    msgs = test_log().get("messages") or []
    check(len(msgs) == 5 and msgs[3]["who"] == "Alex" and msgs[3].get("sticky") is True,
          "R26: the same room key keeps its resident's name")
    check(len(msgs) == 5 and msgs[4]["who"] == "aikos RoomKey Test 2" and not msgs[4].get("sticky"),
          "R26: a second room key does not inherit another key's resident")
    new_test_call()
    transcript("sensor.talk_transcript_door_test", stamp(28), **dict(door, text="Hallo?", message="Hallo?", speaker="", speaker_role=""))
    msgs = test_log().get("messages") or []
    check(len(msgs) == 1 and msgs[0]["who"] == "Besucher" and not msgs[0].get("sticky"),
          "a new call inherits nothing: a door message without a speaker is 'Besucher'")
    call_id = test_log().get("call_id")

    # R22: the chat of a call must never show up in the next one, not even for a moment
    test_call(False)
    log = test_log()
    check(not log.get("messages") and log.get("active") is False, "R22: the log is empty as soon as the call ends")
    transcript("sensor.talk_transcript_door_test", stamp(30), **dict(door, text="Spät.", message="Spät."))
    check(not test_log().get("messages"), "R22: a transcript after the end is not added")
    test_call(True)
    log = test_log()
    check(not log.get("messages") and log.get("call_id") != call_id and log.get("active") is True,
          "the next test call starts empty, new call_id")
    test_call(False)

    live_after = call("/states/sensor.aikos_call_log")
    check(live_after["last_updated"] == live_before["last_updated"], "the live call log did not move")

    print("ALL PASS" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
