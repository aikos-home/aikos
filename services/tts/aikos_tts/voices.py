"""The enrolled voices: one folder per voice with the person's reference recording (`ref.wav`, 24 kHz mono) and
`meta.json` (display name, when). Only the machine that runs the service keeps them; the folder is readable by its user only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path

VOICE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
NAME_MAX = 40
REF_RATE = 24000
MIN_S, MAX_S = 8.0, 60.0     # a reference shorter than 8 s sounds less like the person; longer brings nothing
UPLOAD_MAX = 10 * 1024 * 1024


class VoiceError(ValueError):
    pass


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    created: int
    seconds: float

    @property
    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "created": self.created, "seconds": round(self.seconds, 1)}


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def to_reference(src: Path, dst: Path, ffmpeg: str = "ffmpeg") -> None:
    """Any recording ffmpeg reads → 24 kHz mono 16-bit WAV, leading silence cut, loudness evened out, at most MAX_S."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-t", str(MAX_S + 5),
           "-af", "silenceremove=start_periods=1:start_threshold=-45dB,loudnorm=I=-20:TP=-2",
           "-ac", "1", "-ar", str(REF_RATE), "-sample_fmt", "s16", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not dst.exists():
        raise VoiceError("not a recording: " + (r.stderr or "")[-200:])


class VoiceStore:
    def __init__(self, root: Path, convert=to_reference) -> None:
        self.root = root
        self._convert = convert
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)

    def _dir(self, voice_id: str) -> Path:
        if not VOICE_ID.match(voice_id or ""):
            raise VoiceError("bad voice id")
        return self.root / voice_id

    def get(self, voice_id: str) -> Voice | None:
        d = self._dir(voice_id)
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            return Voice(voice_id, str(meta.get("name") or voice_id), int(meta.get("created") or 0),
                         float(meta.get("seconds") or 0))
        except (OSError, ValueError):
            return None

    def reference(self, voice_id: str) -> Path | None:
        ref = self._dir(voice_id) / "ref.wav"
        return ref if ref.is_file() else None

    def all(self) -> list[Voice]:
        out = []
        for d in sorted(self.root.iterdir()) if self.root.is_dir() else []:
            if d.is_dir() and VOICE_ID.match(d.name):
                v = self.get(d.name)
                if v is not None:
                    out.append(v)
        return out

    def enrol(self, voice_id: str, name: str, audio: bytes) -> Voice:
        """Replaces the voice's reference. The old one stays until the new one is checked."""
        d = self._dir(voice_id)
        if not audio or len(audio) > UPLOAD_MAX:
            raise VoiceError("no recording or too large")
        name = " ".join((name or "").split())[:NAME_MAX] or voice_id
        tmp = self.root / f".{voice_id}.new"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(mode=0o700)
        try:
            (tmp / "upload").write_bytes(audio)
            self._convert(tmp / "upload", tmp / "ref.wav")
            (tmp / "upload").unlink()
            seconds = wav_seconds(tmp / "ref.wav")
            if seconds < MIN_S:
                raise VoiceError(f"too short ({seconds:.1f} s, at least {MIN_S:.0f} s)")
            if seconds > MAX_S + 5:
                raise VoiceError("too long")
            created = int(time.time())
            (tmp / "meta.json").write_text(json.dumps({"name": name, "created": created, "seconds": seconds}),
                                           encoding="utf-8")
            shutil.rmtree(d, ignore_errors=True)
            tmp.rename(d)
            return Voice(voice_id, name, created, seconds)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def delete(self, voice_id: str) -> bool:
        d = self._dir(voice_id)
        if not d.exists():
            return False
        shutil.rmtree(d)
        return True
