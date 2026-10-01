"""Echo helpers: how long a resident talked during a door utterance, household names, dropping repeated sentences."""
import os
import tempfile
import time
import unittest
from pathlib import Path

import _path  # noqa: F401
from aikos_transcriber.echo import is_household, resident_overlap_s, speech_outside_s, strip_echo


class Echo(unittest.TestCase):
    def activity(self, began: float, last: float) -> str:
        f = Path(tempfile.mkdtemp()) / "room_active"
        f.write_text(f"{began:.3f}\n")
        os.utime(f, (last, last))
        return str(f)

    def test_overlap(self):
        now = time.time()
        f = self.activity(now - 10, now - 4)                            # the resident talked from -10 s to -4 s
        self.assertAlmostEqual(resident_overlap_s(f, (now - 6, now)), 2.0, places=1)
        self.assertEqual(resident_overlap_s(f, (now - 3, now)), 0.0)    # the door audio came after
        self.assertEqual(resident_overlap_s("", (now - 3, now)), 0.0)   # no activity file: unknown = 0
        self.assertEqual(resident_overlap_s(str(Path(tempfile.mkdtemp()) / "missing"), (now - 3, now)), 0.0)

    def test_speech_outside(self):
        voiced = [True] * 50 + [False] * 25 + [True] * 50     # 1 s speech, 0.5 s pause, 1 s speech (20 ms frames)
        self.assertAlmostEqual(speech_outside_s(voiced, 100.0, 99.0, 101.0), 0.98, places=1)   # 2nd second after the window
        self.assertEqual(speech_outside_s(voiced, 100.0, 99.0, 102.5), 0.0)                    # all inside (+0.5 s delay)
        self.assertAlmostEqual(speech_outside_s(voiced, 100.0, 102.0, 105.0), 1.3, places=1)   # 1st second + 0.3 s before 101.8

    def test_household(self):
        self.assertTrue(is_household("Jonas", ["Jonas", "Anna"]))
        self.assertTrue(is_household("Jonas Weber", ["jonas"]))
        self.assertFalse(is_household("Paketdienst · DHL", ["Jonas"]))
        self.assertFalse(is_household("Jonas", []))

    def test_strip_echo(self):
        self.assertEqual(strip_echo("Hier ist Jonas, ich komme gleich runter. Alles klar, danke.",
                                    "Hier ist Jonas, ich komme gleich runter."), "Alles klar, danke.")
        self.assertEqual(strip_echo("Ja.", "Ja, ich komme."), "Ja.")       # short sentences stay


if __name__ == "__main__":
    unittest.main()
