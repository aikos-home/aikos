"""R28: a resident's German answer, translated into the visitor's language after the German text (--translate-to-visitor)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import FakeServers, silence, tone, write_wav

PKG_ROOT = Path(__file__).resolve().parent.parent
HEARD = {"room": ("Hier ist Jonas, ich komme gleich runter.", {"text": "x", "language_probabilities": {"de": 0.98}})}


class VisitorTranslation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "token").write_text("t")

    def run_worker(self, fake, flag=True, source="192.0.2.44", llm=None):
        wav = write_wav(self.tmp / "room.wav", silence(0.5), tone(1.2), silence(0.5))
        cmd = [sys.executable, "-m", "aikos_transcriber.worker", str(wav), "--side", "room", "--source-ip", source,
               "--ha-url", fake.url, "--token-file", str(self.tmp / "token"), "--whisper-url", fake.url + "/whisper",
               "--llm-url", llm or fake.url, "--known-names", "Jonas", "--test-sources", "127.0.0.1", "--delete-wav"]
        cmd += ["--translate-to-visitor"] if flag else []
        subprocess.run(cmd, cwd=PKG_ROOT, capture_output=True, timeout=60, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return [(p, b["attributes"]) for p, b in fake.calls if p.startswith("/api/states/")]

    def translations(self, fake):
        return [c for c in fake.chats if c.get("format") != "json" and "aus dem Deutschen" in c["messages"][0]["content"]]

    def test_foreign_call_german_first_then_the_translation(self):
        fake = FakeServers(HEARD, translation="I'll be right down.", visitor_language="en")
        self.addCleanup(fake.close)
        posts = self.run_worker(fake)
        self.assertNotIn("text_visitor", posts[0][1])                                # the German text went out first, unchanged
        self.assertEqual(posts[0][1]["message"], "Ich komme gleich runter.")
        self.assertEqual((posts[1][1]["text_visitor"], posts[1][1]["visitor_language"]), ("I'll be right down.", "en"))
        self.assertEqual(posts[1][1]["speaker"], "Jonas")                            # identity from the German, unchanged
        self.assertIn("Englisch", self.translations(fake)[0]["messages"][0]["content"])
        self.assertEqual(self.translations(fake)[0]["messages"][1]["content"], "Ich komme gleich runter.")
        event = [b for p, b in fake.calls if p == "/api/events/aikos_talk_transcript"][-1]
        self.assertEqual(event["text_visitor"], "I'll be right down.")               # the archive gets it too

    def test_german_call_no_translation_no_extra_post(self):
        fake = FakeServers(HEARD, translation="should not be used", visitor_language="")
        self.addCleanup(fake.close)
        posts = self.run_worker(fake)
        self.assertEqual(self.translations(fake), [])
        self.assertTrue(all("text_visitor" not in a for _, a in posts))
        self.assertEqual(len(posts), 2)                                               # pass 1 + pass 2, as without R28

    def test_option_off_never_asks_the_call_log(self):
        fake = FakeServers(HEARD, translation="should not be used", visitor_language="en")
        self.addCleanup(fake.close)
        posts = self.run_worker(fake, flag=False)
        self.assertFalse(any(g.startswith("/api/states/sensor.aikos_call_log") for g in fake.gets))
        self.assertEqual(self.translations(fake), [])
        self.assertEqual(len(posts), 2)

    def test_llm_down_keeps_the_german_answer(self):
        fake = FakeServers(HEARD, visitor_language="en")
        self.addCleanup(fake.close)
        posts = self.run_worker(fake, llm="http://127.0.0.1:9")
        self.assertTrue(posts and all("text_visitor" not in a for _, a in posts))
        self.assertEqual(posts[0][1]["message"], "Ich komme gleich runter.")

    def test_test_sender_reads_the_test_call_log(self):
        fake = FakeServers(HEARD, translation="I'll be right down.", visitor_language="en")
        self.addCleanup(fake.close)
        posts = self.run_worker(fake, source="127.0.0.1")
        self.assertIn("/api/states/sensor.aikos_call_log_test", fake.gets)
        self.assertEqual({p for p, _ in posts}, {"/api/states/sensor.talk_transcript_test"})


if __name__ == "__main__":
    unittest.main()
