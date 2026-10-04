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

OK, SILENT, CLIPPING = "ok", "silent", "clipping"


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
