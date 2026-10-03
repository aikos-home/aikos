"""Archive lines without Home Assistant (R23): the same fields the former package wrote; visitor text stays data."""
import json
from datetime import datetime, timezone

from custom_components.aikos import call_archive

NOW = datetime(2026, 10, 2, 18, 30, 5, tzinfo=timezone.utc)


def test_call_start_lists_devices_with_firmware():
    line = json.loads(call_archive.call_start(NOW, False, "c1", [{"name": "aikos Intercom Talk", "model": "intercom-talk", "sw": "0.7.4"}]))
    assert line == {"type": "call_start", "t": "2026-10-02T18:30:05+00:00", "test": False, "call_id": "c1",
                    "devices": [{"name": "aikos Intercom Talk", "model": "intercom-talk", "sw": "0.7.4"}]}


def test_call_end_rounds_the_duration():
    assert json.loads(call_archive.call_end(NOW, True, "c1", 57.04))["duration_s"] == 57.0


def test_message_keeps_hostile_text_verbatim_and_names_the_transcriber():
    hostile = "Probelauf mit \"Anführungszeichen\", 'Hochkomma'; rm -rf / $(echo x) `id`"
    line = call_archive.message(NOW, False, "c1", True, {"side": "door", "speaker": "Paketdienst · DHL", "speaker_role": "parcel",
                                                         "message": hostile, "text": hostile, "version": "1.1.1", "created": "t0"})
    d = json.loads(line)
    assert "\n" not in line and d["message"] == hostile and d["transcriber"] == "1.1.1" and d["t"] == "t0" and d["call_id"] == "c1"


def test_message_outside_a_call_has_no_call_id():
    d = json.loads(call_archive.message(NOW, False, "c1", False, {"side": "room"}))
    assert (d["call_id"], d["in_call"], d["t"]) == ("", False, "2026-10-02T18:30:05+00:00")


def test_message_keeps_the_translation_for_the_visitor():
    d = json.loads(call_archive.message(NOW, False, "c1", True, {"side": "room", "text": "Ich komme.", "text_visitor": "I'm coming.",
                                                                 "visitor_language": "en"}))
    assert (d["text_visitor"], d["visitor_language"]) == ("I'm coming.", "en")
