"""Sentences already said, per voice: a checked take is kept, so the same sentence plays at once the next time (the quick
replies, the announcements). The key holds the voice's recording time, so a new recording never plays old takes; deleting
a voice deletes its takes, and another model never plays this one's takes. At most KEEP takes per voice, the least
recently used go first.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

KEEP = 400
TRAILING = " .!?…,;:"


class SpeechCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, voice_id: str, ref_mtime: float, sentence: str, rate: int, model: str, loose: bool = True) -> Path:
        text = " ".join(sentence.split())
        if loose:   # "Ich komme gleich" made while typing still fits "Ich komme gleich!" when it is sent
            text = text.rstrip(TRAILING) + "\x00"
        key = hashlib.sha256(f"{ref_mtime:.3f}\n{rate}\n{model}\n{text}".encode()).hexdigest()[:32]
        return self.root / voice_id / f"{key}.pcm"

    def get(self, voice_id: str, ref_mtime: float, sentence: str, rate: int, model: str = "") -> bytes | None:
        for loose in (True, False):   # False: a take kept by 0.6.2 or older
            p = self._path(voice_id, ref_mtime, sentence, rate, model, loose)
            try:
                data = p.read_bytes()
            except OSError:
                continue
            p.touch()   # used: kept longer
            return data
        return None

    def put(self, voice_id: str, ref_mtime: float, sentence: str, rate: int, pcm: bytes, model: str = "") -> None:
        p = self._path(voice_id, ref_mtime, sentence, rate, model)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(pcm)
        tmp.replace(p)
        self._prune(p.parent)

    def drop(self, voice_id: str) -> None:
        shutil.rmtree(self.root / voice_id, ignore_errors=True)

    def count(self, voice_id: str) -> int:
        d = self.root / voice_id
        return len(list(d.glob("*.pcm"))) if d.is_dir() else 0

    @staticmethod
    def _prune(folder: Path) -> None:
        files = sorted(folder.glob("*.pcm"), key=lambda f: f.stat().st_mtime)
        for f in files[:max(0, len(files) - KEEP)]:
            f.unlink(missing_ok=True)

