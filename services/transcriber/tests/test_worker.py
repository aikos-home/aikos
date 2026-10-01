"""The worker end to end against fake Whisper / LLM / Home Assistant: what reaches HA, and that tests stay out of live entities."""
import os
import subprocess
import sys
import tempfile
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
    "english": ("Hello, this is Anna, I have a parcel for you.",
                {"text": "Hello, this is Anna, I have a parcel for you.", "language_probabilities": {"en": 0.98}}),
    "quiet": ("Haustür-Sprechanlage.", {"text": "", "language_probabilities": {"de": 1.0}}),
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

    def run_worker(self, name, side, source, quiet=False):
        self.fake.calls.clear()
        wav = write_wav(self.tmp / f"{name}.wav", silence(0.5), silence(1.2) if quiet else tone(1.2), silence(0.5))
        cmd = [sys.executable, "-m", "aikos_transcriber.worker", str(wav), "--side", side, "--source-ip", source,
               "--ha-url", self.fake.url, "--token-file", str(self.tmp / "token"), "--whisper-url", self.fake.url + "/whisper",
               "--llm-url", self.fake.url, "--known-names", "Jonas", "--test-sources", "127.0.0.1", "--delete-wav"]
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
        self.assertEqual(self.run_worker("quiet", "door", "192.0.2.62", quiet=True), [])

    def test_foreign_language_is_translated(self):
        a = self.states(self.run_worker("english", "door", "192.0.2.62"))[-1][1]
        self.assertEqual((a["language"], a["language_name"]), ("en", "Englisch"))
        self.assertEqual(a["text"], "Hallo, hier ist Anna, ich habe ein Paket für Sie.")
        self.assertEqual(a["text_original"], "Hello, this is Anna, I have a parcel for you.")


if __name__ == "__main__":
    unittest.main()
