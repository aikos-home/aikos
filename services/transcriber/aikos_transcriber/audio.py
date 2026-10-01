"""Audio helpers: is there speech in a recording, padding for Whisper, WAV from raw PCM.

Part of the aikos transcriber (split from roomkey tools/transcribe_publish.py and talk_live.py at d0d52b9, code unchanged)."""
from __future__ import annotations

import array
import io
import math
import wave
from pathlib import Path

RATE = 16000


def has_speech(wav: Path, min_s: float = 0.3) -> bool:
    """At least min_s of 20 ms frames clearly above the recording's own noise floor (10th percentile + 12 dB),
    and not just quiet hiss (> -50 dBFS)."""
    with wave.open(str(wav)) as w:
        rate, n = w.getframerate(), w.getnframes()
        pcm = w.readframes(n)
    import array
    import math
    x = array.array("h", pcm)
    step = rate // 50
    db = []
    for i in range(0, len(x) - step + 1, step):
        fr = x[i:i + step]
        db.append(20 * math.log10(math.sqrt(sum(v * v for v in fr) / step) / 32768 + 1e-9))
    if not db:
        return False
    floor = sorted(db)[len(db) // 10]
    loud = sum(1 for d in db if d > max(floor + 12.0, -50.0))
    return loud * 0.02 >= min_s


def padded(wav: Path) -> bytes:
    """The WAV with 0.3 s of silence before and 1 s after: Whisper drops words that touch the edges."""
    with wave.open(str(wav)) as w:
        rate, pcm = w.getframerate(), w.readframes(w.getnframes())
        b = io.BytesIO()
        with wave.open(b, "wb") as o:
            o.setnchannels(w.getnchannels()); o.setsampwidth(w.getsampwidth()); o.setframerate(rate)
            o.writeframes(b"\x00\x00" * int(0.3 * rate) + pcm + b"\x00\x00" * rate)
    return b.getvalue()


def has_speech_pcm(pcm: bytes, min_s: float = 0.3) -> bool:
    """At least min_s of 20 ms frames clearly above the recording's own noise floor (see transcribe_publish)."""
    x = array.array("h", pcm)
    step = RATE // 50
    db = [20 * math.log10(math.sqrt(sum(v * v for v in x[i:i + step]) / step) / 32768 + 1e-9)
          for i in range(0, len(x) - step + 1, step)]
    if not db:
        return False
    floor = sorted(db)[len(db) // 10]
    return sum(1 for d in db if d > max(floor + 12.0, -50.0)) * 0.02 >= min_s


def wav_bytes(pcm: bytes) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(b"\x00\x00" * int(0.3 * RATE) + pcm + b"\x00\x00" * (RATE // 2))
    return b.getvalue()
