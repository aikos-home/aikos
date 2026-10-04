"""Receiver over real UDP on localhost: one recording per utterance, and the activity-file contract between the two sides
(content = start time, mtime = last audio, `_test` suffix for test senders), which the door side's echo guard reads."""
import os
import socket
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

import _path  # noqa: F401
from aikos_transcriber import receiver
from aikos_transcriber.echo import drop_echo, resident_talk
from helpers import rtp, silence, tone


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Receiver(unittest.TestCase):
    def start(self, *extra):
        self.tmp = Path(tempfile.mkdtemp())
        self.port = free_port()
        self.activity = self.tmp / "room_active"
        args = ["--port", str(self.port), "--out", str(self.tmp / "rec"), "--activity-file", str(self.activity)] + list(extra)
        threading.Thread(target=receiver.main, args=(args,), daemon=True).start()
        time.sleep(0.3)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(self.sock.close)

    def send_utterance(self, seconds: float = 1.0):
        x = tone(seconds)
        for k in range(len(x) // 320):
            self.sock.sendto(rtp(k + 1, x[k * 320:(k + 1) * 320]), ("127.0.0.1", self.port))
            time.sleep(0.002)
        self.sock.sendto(rtp(len(x) // 320 + 1, silence(0.0), pt=13), ("127.0.0.1", self.port))   # comfort noise = released
        time.sleep(0.5)

    def test_one_recording_per_utterance(self):
        """Two utterances within the same second: two recordings, the first one intact (regression: same name, overwritten)."""
        self.start("--test-sources", "")
        self.send_utterance(1.0)
        self.send_utterance(0.6)
        wavs = sorted((self.tmp / "rec").glob("*.wav"), key=lambda p: p.stat().st_mtime)
        self.assertEqual(len(wavs), 2)
        lengths = []
        for p in wavs:
            with wave.open(str(p)) as w:
                self.assertEqual((w.getframerate(), w.getnchannels()), (16000, 1))
                lengths.append(round(w.getnframes() / 16000, 1))
        self.assertEqual(lengths, [1.0, 0.6])

    def test_activity_contract_live_sender(self):
        self.start("--test-sources", "")                                  # 127.0.0.1 counts as a real resident here
        before = time.time()
        self.send_utterance(1.0)
        self.assertTrue(self.activity.exists())
        self.assertFalse(Path(str(self.activity) + "_test").exists())
        start, last = resident_talk(str(self.activity))
        self.assertGreaterEqual(start, before - 0.1)                       # content = when the resident began
        self.assertGreaterEqual(last, start)                               # mtime = last audio
        self.assertLess(time.time() - last, 2.0)

    def test_activity_contract_test_sender(self):
        self.start("--test-sources", "127.0.0.1")
        self.send_utterance(1.0)
        self.assertFalse(self.activity.exists())                          # a test sender never marks a real resident
        self.assertTrue(Path(str(self.activity) + "_test").exists())


class DoorTurn(unittest.TestCase):
    """Door side (--split-on-silence): a resident who starts talking ends the visitor's utterance at once (04.10.: the turn gap
    was shorter than --silence-s, the resident's echo kept the segment running to --max-s, the visitor's text came 21 s late)."""

    def start(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.port = free_port()
        self.quiet = self.tmp / "room_active"
        args = ["--port", str(self.port), "--out", str(self.tmp / "rec"), "--split-on-silence", "--test-sources", "",
                "--live-quiet-file", str(self.quiet)]
        threading.Thread(target=receiver.main, args=(args,), daemon=True).start()
        time.sleep(0.3)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(self.sock.close)
        self.seq = 0

    def stream(self, x):                                                  # the door's continuous stream, real time
        for k in range(len(x) // 320):
            self.seq += 1
            self.sock.sendto(rtp(self.seq, x[k * 320:(k + 1) * 320]), ("127.0.0.1", self.port))
            time.sleep(0.02)

    def recordings(self):
        out = []
        for p in sorted((self.tmp / "rec").glob("*.wav"), key=lambda p: p.stat().st_mtime):
            with wave.open(str(p)) as w:
                out.append(round(w.getnframes() / 16000, 1))
        return out

    def test_a_resident_taking_the_turn_ends_the_visitors_utterance(self):
        self.start()
        self.stream(silence(0.6))
        self.stream(tone(1.0))                                            # the visitor
        self.quiet.write_text(f"{time.time():.3f}\n")                    # a resident starts talking (room side)
        self.stream(tone(1.0))                                            # the resident's echo from the door speaker
        self.stream(silence(2.0))
        time.sleep(0.5)
        lengths = self.recordings()
        self.assertEqual(len(lengths), 2, lengths)                        # cut at the turn, not one 15 s block
        self.assertLessEqual(lengths[0], 1.6)                             # the visitor (+ pre-roll), sent at once

    def test_an_older_resident_turn_does_not_cut(self):
        self.start()
        self.quiet.write_text(f"{time.time() - 5:.3f}\n")                # the resident talked before the visitor began
        self.stream(silence(0.6))
        self.stream(tone(1.5))
        self.stream(silence(2.0))
        time.sleep(0.5)
        self.assertEqual(len(self.recordings()), 1)


class RecordingNames(unittest.TestCase):
    def test_same_second_same_sender_gets_a_new_name(self):
        out = Path(tempfile.mkdtemp())
        with mock.patch("time.strftime", return_value="20990101_120000"):
            first = receiver.Recording(out, ("192.0.2.44", 40000))
            second = receiver.Recording(out, ("192.0.2.44", 40000))
            third = receiver.Recording(out, ("192.0.2.44", 40000))
        for r in (first, second, third):
            r.wav.close()
        self.assertEqual([r.path.name for r in (first, second, third)],
                         ["roomkey_20990101_120000_192-0-2-44.wav", "roomkey_20990101_120000_192-0-2-44_2.wav",
                          "roomkey_20990101_120000_192-0-2-44_3.wav"])


class EchoGuard(unittest.TestCase):
    def test_no_overlap_keeps_text_without_asking_ha(self):
        tmp = Path(tempfile.mkdtemp())
        act = tmp / "room_active"
        act.write_text(f"{time.time() - 100:.3f}\n")
        os.utime(act, (time.time() - 99, time.time() - 99))               # the resident talked long before the door audio
        now = time.time()
        self.assertEqual(drop_echo("Hallo, wer ist da?", "http://ha.invalid", "t", (now - 2, now), str(act)),
                         "Hallo, wer ist da?")

    def test_unknown_activity(self):
        self.assertEqual(resident_talk(str(Path(tempfile.mkdtemp()) / "missing")), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
