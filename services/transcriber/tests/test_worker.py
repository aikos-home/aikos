"""The worker end to end against fake Whisper / LLM / Home Assistant: what reaches HA, and that tests stay out of live entities."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import FakeServers, silence, tone, write_wav

PKG_ROOT = Path(__file__).resolve().parent.parent
HEARD = {
    "room": ("Hier ist Jonas, ich komme gleich runter.", {"text": "x", "language_probabilities": {"de": 0.97}}),
    "door": ("Guten Tag, Paketdienst von DHL, ich habe ein Paket für Sie.", {"text": "x", "language_probabilities": {"de": 0.99}}),
    "help": ("Hilfe! Mein Mann ist gestürzt, bitte rufen Sie einen Krankenwagen!", {"text": "x", "language_probabilities": {"de": 0.99}}),
    "noise": ("[Musik]", {"text": "[Musik]", "language_probabilities": {"de": 0.5}}),
    "ardtext": ("ARD Text im Auftrag", {"text": "ARD Text im Auftrag", "language_probabilities": {"de": 0.6}}),  # R24
    "english": ("Hello, this is Anna, I have a parcel for you.",
                {"text": "Hello, this is Anna, I have a parcel for you.", "language_probabilities": {"en": 0.98}}),
    "quiet": ("Haustür-Sprechanlage.", {"text": "", "language_probabilities": {"de": 1.0}}),
    "resident": ("Hier ist Jonas, ich komme gleich runter.", {"text": "x", "language_probabilities": {"de": 0.98}}),
    "echo": ("Das war nicht.", {"text": "x", "language_probabilities": {"de": 0.9}}),
    "after": ("Alles klar, ich warte hier unten.", {"text": "x", "language_probabilities": {"de": 0.97}}),
}


class Worker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeServers(HEARD, translation="Hallo, hier ist Anna, ich habe ein Paket für Sie.")
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / "token").write_text("t")

    @classmethod
    def tearDownClass(cls):
        cls.fake.close()

    def run_worker(self, name, side, source, quiet=False, llm=None, activity=None, parts=None):
        self.fake.calls.clear()
        wav = write_wav(self.tmp / f"{name}.wav", *(parts or (silence(0.5), silence(1.2) if quiet else tone(1.2), silence(0.5))))
        cmd = [sys.executable, "-m", "aikos_transcriber.worker", str(wav), "--side", side, "--source-ip", source,
               "--ha-url", self.fake.url, "--token-file", str(self.tmp / "token"), "--whisper-url", self.fake.url + "/whisper",
               "--llm-url", llm or self.fake.url, "--known-names", "Jonas", "--test-sources", "127.0.0.1", "--delete-wav"]
        if activity:
            cmd += ["--activity-file", str(activity)]
        subprocess.run(cmd, cwd=PKG_ROOT, capture_output=True, timeout=60, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertFalse(wav.exists(), "the recording is deleted when done")
        return list(self.fake.calls)

    def states(self, calls):
        return [(p, b["attributes"]) for p, b in calls if p.startswith("/api/states/")]

    def test_room_live_sender(self):
        calls = self.run_worker("room", "room", "192.0.2.44")
        posts = self.states(calls)
        self.assertEqual({p for p, _ in posts}, {"/api/states/sensor.talk_transcript"})
        a = posts[-1][1]
        self.assertEqual((a["speaker"], a["speaker_role"], a["message"]), ("Jonas", "name", "Ich komme gleich runter."))
        self.assertEqual(a["device"], "aikos RoomKey Test")                # found by the sender's IP sensor
        self.assertIn(("/api/events/aikos_talk_transcript"), [p for p, _ in calls])

    def test_door_role_and_urgent(self):
        a = self.states(self.run_worker("door", "door", "192.0.2.62"))[-1][1]
        self.assertEqual((a["speaker"], a["speaker_role"], a["urgent"]), ("Paketdienst · DHL", "parcel", False))
        h = self.states(self.run_worker("help", "door", "192.0.2.62"))[-1][1]
        self.assertEqual((h["speaker_role"], h["urgent"]), ("emergency", True))

    def test_test_sender_never_reaches_live_entities(self):
        calls = self.run_worker("door", "door", "127.0.0.1")
        paths = {p for p, _ in calls}
        self.assertEqual(paths, {"/api/states/sensor.talk_transcript_door_test", "/api/events/aikos_talk_transcript_test"})

    def test_nothing_published_for_noise_or_silence(self):
        self.assertEqual(self.run_worker("noise", "door", "192.0.2.62"), [])
        self.assertEqual(self.run_worker("ardtext", "door", "192.0.2.62"), [])      # R24: a subtitle credit, never shown
        self.assertEqual(self.run_worker("quiet", "door", "192.0.2.62", quiet=True), [])

    def test_foreign_language_is_translated(self):
        a = self.states(self.run_worker("english", "door", "192.0.2.62"))[-1][1]
        self.assertEqual((a["language"], a["language_name"]), ("en", "Englisch"))
        self.assertEqual(a["text"], "Hallo, hier ist Anna, ich habe ein Paket für Sie.")
        self.assertEqual(a["text_original"], "Hello, this is Anna, I have a parcel for you.")

    def test_resident_words_heard_at_the_door_are_no_visitor(self):
        # system test W1: the key's mic sent silence, so no room transcript could filter the door mic hearing the resident
        act = self.tmp / "room_active"
        act.write_text(f"{time.time() - 10:.3f}\n")         # a resident has been talking for 10 s and still talks
        self.assertEqual(self.states(self.run_worker("resident", "door", "192.0.2.62", activity=act)), [])

    def resident(self, began_ago: float, last_ago: float):
        act = self.tmp / "room_active"
        now = time.time()
        act.write_text(f"{now - began_ago:.3f}\n")
        os.utime(act, (now - last_ago, now - last_ago))
        return act

    def test_echo_inside_the_residents_talk_is_dropped_whatever_whisper_heard(self):
        # live test 01.10. 18:58: the door mic heard "Ich kann gerade nicht" and Whisper made "Das war nicht." of it
        act = self.resident(began_ago=10, last_ago=0)                     # the resident talks all through the door audio
        self.assertEqual(self.states(self.run_worker("echo", "door", "192.0.2.62", activity=act)), [])

    def test_visitor_speaking_after_the_resident_stops_is_kept(self):
        # door audio 3.9 s: words at 0.5–1.7 s (during the resident's talk) and 2.2–3.4 s (after it ended)
        act = self.resident(began_ago=10, last_ago=2.9)
        parts = (silence(0.5), tone(1.2), silence(0.5), tone(1.2), silence(0.5))
        a = self.states(self.run_worker("after", "door", "192.0.2.62", activity=act, parts=parts))[-1][1]
        self.assertEqual(a["text"], "Alles klar, ich warte hier unten.")

    def test_household_name_at_the_door_without_a_resident_talking_is_shown(self):
        a = self.states(self.run_worker("resident", "door", "192.0.2.62"))[-1][1]    # forgot the keys: fine
        self.assertEqual((a["speaker"], a["speaker_role"]), ("Jonas", "name"))

    def test_published_even_when_the_llm_is_down(self):
        a = self.states(self.run_worker("english", "door", "192.0.2.62", llm="http://127.0.0.1:9"))[-1][1]
        self.assertEqual(a["text"], "Hello, this is Anna, I have a parcel for you.")      # untranslated, but there
        d = self.states(self.run_worker("door", "door", "192.0.2.62", llm="http://127.0.0.1:9"))[-1][1]
        self.assertEqual(d["speaker_role"], "parcel")                                     # the rules still know


if __name__ == "__main__":
    unittest.main()
