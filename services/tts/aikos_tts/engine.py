"""Speech from text in a person's voice. The model (Chatterbox multilingual, MIT licence, with its inaudible watermark that
marks the audio as synthetic) is loaded once and kept; one synthesis at a time. Text is split into sentences so a long note
does not run over the model's limit.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

SENTENCE = re.compile(r"(?<=[.!?…])\s+")
PIECE_MAX = 220
PAUSE_S = 0.15


def sentences(text: str) -> list[str]:
    text = " ".join((text or "").split())
    out: list[str] = []
    for s in SENTENCE.split(text):
        while len(s) > PIECE_MAX:   # a very long sentence: cut at the last comma or space before the limit
            cut = max(s.rfind(",", 0, PIECE_MAX), s.rfind(" ", 0, PIECE_MAX))
            cut = cut if cut > 40 else PIECE_MAX
            out.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        if s:
            out.append(s)
    return out


def to_pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


class Engine:
    """`synthesize(text, reference)` → 16-bit mono PCM at `rate`. Subclasses provide `_generate`."""

    rate = 24000
    name = "engine"

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def synthesize(self, text: str, reference: Path) -> bytes:
        parts = sentences(text)
        if not parts:
            return b""
        pause = np.zeros(int(self.rate * PAUSE_S), dtype=np.float32)
        with self._lock:
            pieces = []
            for i, s in enumerate(parts):
                if i:
                    pieces.append(pause)
                pieces.append(self._generate(s, reference))
        return to_pcm16(np.concatenate(pieces))

    def _generate(self, text: str, reference: Path) -> np.ndarray:  # pragma: no cover - the real model
        raise NotImplementedError


class ChatterboxEngine(Engine):
    name = "chatterbox-multilingual"

    def __init__(self, device: str = "", language: str = "de") -> None:
        super().__init__()
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        self._torch = torch
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        self.rate = self.model.sr
        self.language = language
        self._conds: dict[Path, tuple[float, object]] = {}

    def _generate(self, text: str, reference: Path) -> np.ndarray:  # pragma: no cover - needs the model
        mtime = reference.stat().st_mtime
        cached = self._conds.get(reference)
        if cached is None or cached[0] != mtime:   # a re-recorded voice is picked up at once
            self.model.prepare_conditionals(str(reference))
            self._conds[reference] = (mtime, self.model.conds)
        self.model.conds = self._conds[reference][1]
        with self._torch.inference_mode():
            wav = self.model.generate(text, language_id=self.language)
        return wav.squeeze(0).detach().cpu().numpy().astype(np.float32)


class FakeEngine(Engine):
    """For tests: a tone per character, so length follows the text."""

    name = "fake"

    def __init__(self, on_call: Callable[[str, Path], None] | None = None) -> None:
        super().__init__()
        self.rate = 16000
        self.calls: list[tuple[str, str]] = []
        self._on_call = on_call

    def _generate(self, text: str, reference: Path) -> np.ndarray:
        self.calls.append((text, reference.parent.name))
        if self._on_call:
            self._on_call(text, reference)
        t = np.arange(int(self.rate * 0.02 * len(text))) / self.rate
        return (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
