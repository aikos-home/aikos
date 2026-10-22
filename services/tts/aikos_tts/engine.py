"""Speech from text in a person's voice. The model (Chatterbox multilingual, MIT licence, with its inaudible watermark that
marks the audio as synthetic) is loaded once and kept; one synthesis at a time. Two ways to run it: PyTorch on MPS
(`chatterbox`) or Apple's MLX (`chatterbox-mlx`, about three times as fast on an M2 Max; the watermark is added here, the
MLX port has none). Text is split into sentences so a long note
does not run over the model's limit. With a checker, every sentence is written back and compared with the text (verify.py):
the model only gives the voice, it never decides what is said.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .cache import SpeechCache
from .verify import Verdict, WhisperChecker

SENTENCE = re.compile(r"(?<=[.!?…])\s+")
PIECE_MAX = 220
PAUSE_S = 0.15
TEMPERATURES = (0.6, 0.45, 0.3)   # each further take of a sentence a little less free
FADE_S = 0.02


class SpeechError(RuntimeError):
    """The text could not be said faithfully: say nothing (the door shows the text only)."""


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

    def __init__(self, checker: WhisperChecker | None = None) -> None:
        self._lock = threading.Lock()
        self.checker = checker
        self.cache: SpeechCache | None = None

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
                pieces.append(self._take(s, reference))
        return to_pcm16(np.concatenate(pieces))

    def _take(self, sentence: str, reference: Path) -> np.ndarray:
        if self.cache is None:
            return self._make(sentence, reference)
        voice, mtime = reference.parent.name, reference.stat().st_mtime
        hit = self.cache.get(voice, mtime, sentence, self.rate, self.name)
        if hit is not None:
            return np.frombuffer(hit, dtype="<i2").astype(np.float32) / 32767.0
        samples = self._make(sentence, reference)
        self.cache.put(voice, mtime, sentence, self.rate, to_pcm16(samples), self.name)
        return samples

    def _make(self, sentence: str, reference: Path) -> np.ndarray:
        if self.checker is None:
            return self._generate(sentence, reference, TEMPERATURES[0])
        last = ""
        for temperature in TEMPERATURES:
            samples = self._generate(sentence, reference, temperature)
            verdict = self.checker.check(sentence, to_pcm16(samples), self.rate)
            if verdict.ok and verdict.cut_s is not None:
                samples = samples[:int(verdict.cut_s * self.rate)].copy()
                fade = min(len(samples), int(FADE_S * self.rate))
                if fade:
                    samples[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
                # word times are rough: what is left must now be the text and nothing else
                verdict = self.checker.check(sentence, to_pcm16(samples), self.rate)
                if verdict.cut_s is not None:
                    verdict = Verdict(False, None, verdict.coverage, verdict.heard)
            if verdict.ok:
                return samples
            last = verdict.heard
        raise SpeechError(f"could not say {sentence!r} (heard {last!r})")

    def _generate(self, text: str, reference: Path, temperature: float) -> np.ndarray:  # pragma: no cover - the real model
        raise NotImplementedError

    def warm_up(self, reference: Path) -> None:
        """One sentence nobody hears, right after loading: the first take after a start is slow (6 s instead of 2)."""
        with self._lock:
            self._generate("Hallo.", reference, TEMPERATURES[0])


class ChatterboxEngine(Engine):
    name = "chatterbox-multilingual"

    def __init__(self, device: str = "", language: str = "de", checker: WhisperChecker | None = None) -> None:
        super().__init__(checker)
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        self._torch = torch
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        self.rate = self.model.sr
        self.language = language
        self._conds: dict[Path, tuple[float, object]] = {}

    def _generate(self, text: str, reference: Path, temperature: float) -> np.ndarray:  # pragma: no cover - the model
        mtime = reference.stat().st_mtime
        cached = self._conds.get(reference)
        if cached is None or cached[0] != mtime:   # a re-recorded voice is picked up at once
            self.model.prepare_conditionals(str(reference))
            self._conds[reference] = (mtime, self.model.conds)
        self.model.conds = self._conds[reference][1]
        with self._torch.inference_mode():
            wav = self.model.generate(text, language_id=self.language, temperature=temperature)
        return wav.squeeze(0).detach().cpu().numpy().astype(np.float32)


class MlxChatterboxEngine(Engine):
    """Chatterbox multilingual on MLX (mlx-audio). Same voices, same check; measured 22.10.: 1.5–2.6 s per sentence
    instead of 5–8 s, 8 of 8 takes faithful at the first try."""

    name = "chatterbox-mlx"
    REPO = "mlx-community/chatterbox-multilingual-v3"

    def __init__(self, language: str = "de", checker: WhisperChecker | None = None, repo: str = "") -> None:
        super().__init__(checker)
        import perth
        from mlx_audio.tts.utils import load_model
        self.model = load_model(repo or self.REPO)
        self.rate = self.model.sample_rate
        self.language = language
        self._watermark = perth.PerthImplicitWatermarker()
        self._conds: dict[Path, tuple[float, object]] = {}

    def _generate(self, text: str, reference: Path, temperature: float) -> np.ndarray:  # pragma: no cover - the model
        mtime = reference.stat().st_mtime
        cached = self._conds.get(reference)
        if cached is None or cached[0] != mtime:   # a re-recorded voice is picked up at once
            self._conds[reference] = (mtime, self.model.prepare_conditionals(str(reference), self.rate, exaggeration=0.1))
        parts = [np.asarray(r.audio, dtype=np.float32) for r in self.model.generate(
            text, conds=self._conds[reference][1], lang_code=self.language, temperature=temperature, verbose=False)]
        wav = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return np.asarray(self._watermark.apply_watermark(wav, sample_rate=self.rate), dtype=np.float32)


class FakeEngine(Engine):
    """For tests: a tone per character, so length follows the text."""

    name = "fake"

    def __init__(self, on_call: Callable[[str, Path], None] | None = None, checker=None) -> None:
        super().__init__(checker)
        self.rate = 16000
        self.calls: list[tuple[str, str]] = []
        self.temperatures: list[float] = []
        self._on_call = on_call

    def _generate(self, text: str, reference: Path, temperature: float = TEMPERATURES[0]) -> np.ndarray:
        self.calls.append((text, reference.parent.name))
        self.temperatures.append(temperature)
        if self._on_call:
            self._on_call(text, reference)
        t = np.arange(int(self.rate * 0.02 * len(text))) / self.rate
        return (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
