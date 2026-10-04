"""Mic health (W3): is a recording what a working microphone sends? Pure functions, no network.

A loose or broken mic wire shows up as digital silence (the data line pulled low: all zeros) or as garbage at full scale
(a floating data line: clipping). Found by the system test of 01.10. on the bench; now every recording is checked.
"""
from __future__ import annotations

import array
import math
from dataclasses import dataclass

RATE = 16000
MIN_S = 0.5                 # shorter recordings (a tap) say nothing about the mic
SILENT_PEAK_DB = -90.0      # a working mic always has some noise; its peaks never stay below this
CLIP_LEVEL = 32700          # |sample| at or above this counts as clipped
CLIP_RATIO = 0.01           # 1 % clipped samples: speech at a sane gain never does that
NOISE_RMS_DB = -10.0        # garbage behind the devices' ~-2 dBFS limiter never clips but stays this loud; speech is ~-25
DIGITAL_SILENCE_DB = -100.0 # a 20 ms packet below this is digital silence (zeros), not a quiet room

OK, SILENT, CLIPPING, NOISE = "ok", "silent", "clipping", "noise"


@dataclass
class MicStats:
    duration_s: float
    zero_ratio: float
    clip_ratio: float
    peak_db: float
    rms_db: float

    @property
    def verdict(self) -> str:
        if self.peak_db <= SILENT_PEAK_DB:
            return SILENT
        if self.clip_ratio >= CLIP_RATIO:
            return CLIPPING
        if self.rms_db > NOISE_RMS_DB:
            return NOISE
        return OK

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "duration_s": round(self.duration_s, 1), "zero_ratio": round(self.zero_ratio, 3),
                "clip_ratio": round(self.clip_ratio, 4), "peak_db": round(self.peak_db, 1), "rms_db": round(self.rms_db, 1)}


def _db(value: float) -> float:
    return 20 * math.log10(value / 32768 + 1e-9)


def stats(pcm: bytes) -> MicStats | None:
    """Stats of 16-bit mono PCM at 16 kHz; None when it is too short to judge."""
    x = array.array("h", pcm)
    n = len(x)
    if n < MIN_S * RATE:
        return None
    zeros = clipped = peak = 0
    squares = 0
    for v in x:
        a = -v if v < 0 else v
        if a == 0:
            zeros += 1
        elif a >= CLIP_LEVEL:
            clipped += 1
        if a > peak:
            peak = a
        squares += v * v
    return MicStats(duration_s=n / RATE, zero_ratio=zeros / n, clip_ratio=clipped / n, peak_db=_db(peak),
                    rms_db=_db(math.sqrt(squares / n)))


class SilenceWatch:
    """Door side: a mic sending only digital silence (data line on GND) starts no recording, so the receiver watches the stream.

    note() returns the silent seconds once per episode, when an unbroken run of digital-silence packets from one sender reaches
    after_s. A real packet, a gap in the stream (> gap_s, e.g. the next call) or an excused moment (a resident talks: the door may
    mute its mic while its speaker plays) ends the episode.
    """

    def __init__(self, after_s: float = 10.0, gap_s: float = 2.0):
        self.after_s, self.gap_s = after_s, gap_s
        self.since: dict = {}
        self.last: dict = {}
        self.reported: set = set()

    def note(self, src, db: float, now: float, excused: bool = False):
        last = self.last.get(src)
        self.last[src] = now
        if (last is not None and now - last > self.gap_s) or excused or db > DIGITAL_SILENCE_DB:
            self.since.pop(src, None)
            self.reported.discard(src)
            if excused or db > DIGITAL_SILENCE_DB:
                return None
        start = self.since.setdefault(src, now)
        if src not in self.reported and now - start >= self.after_s:
            self.reported.add(src)
            return now - start
        return None
