"""Speech detection and padding: a click or hiss is not speech, 0.3 s of voice is."""
import tempfile
import unittest
import wave
from pathlib import Path

import _path  # noqa: F401
from aikos_transcriber.audio import RATE, has_speech, has_speech_pcm, padded
from helpers import silence, tone, write_wav


class Speech(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_voice_is_speech(self):
        wav = write_wav(self.tmp / "voice.wav", silence(0.5), tone(1.0), silence(0.5))
        self.assertTrue(has_speech(wav))
        self.assertTrue(has_speech_pcm((silence(0.5) + tone(1.0) + silence(0.5)).tobytes()))

    def test_silence_and_a_click_are_not(self):
        click = silence(1.2)
        for i in range(2000, 2040):
            click[i] = 6000 if i % 2 else -6000
        wav = write_wav(self.tmp / "click.wav", click)
        self.assertFalse(has_speech(wav))
        self.assertFalse(has_speech_pcm(click.tobytes()))
        self.assertFalse(has_speech(write_wav(self.tmp / "empty.wav", silence(0.0))))

    def test_too_short(self):
        self.assertFalse(has_speech(write_wav(self.tmp / "short.wav", silence(0.5), tone(0.2), silence(0.5))))

    def test_padding(self):
        wav = write_wav(self.tmp / "p.wav", tone(1.0))
        with wave.open(str(wav)) as w, wave.open(__import__("io").BytesIO(padded(wav))) as p:
            self.assertEqual(p.getnframes(), w.getnframes() + int(0.3 * RATE) + RATE)


if __name__ == "__main__":
    unittest.main()
