"""W3 mic health: the verdict of one recording (pure) and the worker's event (with fake Home Assistant)."""
import array
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from aikos_transcriber.mic import CLIPPING, OK, SILENT, stats
from helpers import FakeServers, silence, tone, write_wav

PKG_ROOT = Path(__file__).resolve().parent.parent


def pcm(*parts) -> bytes:
    x = array.array("h")
    for p in parts:
        x.extend(p)
    return x.tobytes()


def noise_floor(seconds: float) -> array.array:
    """A working mic in a quiet room: a little hiss, never exactly zero for long."""
    return array.array("h", [((i * 7919) % 41) - 20 for i in range(int(seconds * 16000))])


class Verdict(unittest.TestCase):
    def test_dead_mic_all_zeros_is_silent(self):
        self.assertEqual(stats(pcm(silence(1.0))).verdict, SILENT)

    def test_quiet_room_is_ok(self):
        self.assertEqual(stats(pcm(noise_floor(1.0))).verdict, OK)

    def test_speech_is_ok(self):
        s = stats(pcm(noise_floor(0.3), tone(1.0), noise_floor(0.3)))
        self.assertEqual(s.verdict, OK)
        self.assertLess(s.clip_ratio, 0.001)

    def test_floating_data_line_is_clipping(self):
        garbage = array.array("h", [32767 if (i // 3) % 2 else -32768 for i in range(16000)])
        self.assertEqual(stats(garbage.tobytes()).verdict, CLIPPING)

    def test_a_tap_is_not_judged(self):
        self.assertIsNone(stats(pcm(silence(0.3))))


class WorkerEvent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        heard = {"room": ("Hier ist Jonas, ich komme gleich runter.", {"text": "x", "language_probabilities": {"de": 0.98}}),
                 "dead": ("", {"text": "", "language_probabilities": {"de": 1.0}})}
        cls.fake = FakeServers(heard)
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / "token").write_text("t")

    @classmethod
    def tearDownClass(cls):
        cls.fake.close()

    def run_worker(self, name, parts, flag=True, source="192.0.2.44"):
        self.fake.calls.clear()
        wav = write_wav(self.tmp / f"{name}.wav", *parts)
        cmd = [sys.executable, "-m", "aikos_transcriber.worker", str(wav), "--side", "room", "--source-ip", source,
               "--ha-url", self.fake.url, "--token-file", str(self.tmp / "token"), "--whisper-url", self.fake.url + "/whisper",
               "--no-llm", "--known-names", "Jonas", "--test-sources", "127.0.0.1", "--delete-wav"]
        cmd += ["--mic-check"] if flag else []
        subprocess.run(cmd, cwd=PKG_ROOT, capture_output=True, timeout=60, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return [(p, b) for p, b in self.fake.calls if p.startswith("/api/events/aikos_mic_check")]

    def test_dead_mic_reports_silent_although_nothing_is_published(self):
        events = self.run_worker("dead", (silence(1.5),))
        self.assertEqual([(p, b["verdict"]) for p, b in events], [("/api/events/aikos_mic_check", "silent")])
        self.assertEqual(events[0][1]["device"], "aikos RoomKey Test")             # named by its IP sensor
        self.assertFalse(any(p.startswith("/api/states/sensor.talk_transcript") for p, _ in self.fake.calls))

    def test_a_working_mic_reports_ok_after_the_text(self):
        self.run_worker("room", (silence(0.5), tone(1.2), silence(0.5)))
        paths = [p for p, _ in self.fake.calls]
        self.assertEqual(paths[-1], "/api/events/aikos_mic_check")                 # last: the text went out first
        self.assertEqual(self.fake.calls[-1][1]["verdict"], "ok")

    def test_option_off_reports_nothing(self):
        self.assertEqual(self.run_worker("dead", (silence(1.5),), flag=False), [])

    def test_test_sender_reports_to_the_test_event(self):
        events = self.run_worker("dead", (silence(1.5),), source="127.0.0.1")
        self.assertEqual([p for p, _ in events], ["/api/events/aikos_mic_check_test"])


if __name__ == "__main__":
    unittest.main()
