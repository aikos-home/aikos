"""The voices as one archive, to move them to another machine (or to keep a copy). The owner, 22.10.: „stimmen export ist
echt nicht so brisant. ist ja alles im heimnetz." So it is a plain tar.gz of the voices folder (0600), not encrypted; the
backup of the state folder (Time Machine) covers the voices anyway.

    python -m aikos_tts export FILE
    python -m aikos_tts import FILE [--replace]
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path


class VaultError(Exception):
    pass


def export(voices: Path, out: Path) -> int:
    """Writes the archive (0600). Returns how many voices are in it."""
    folders = sorted(p for p in voices.iterdir() if p.is_dir() and not p.name.startswith(".")) if voices.is_dir() else []
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w:gz") as tar:
        for f in folders:
            tar.add(f, arcname=f.name)
    return len(folders)


def restore(src: Path, voices: Path, replace: bool = False) -> list[str]:
    """Puts the archive's voices into the voices folder. A voice that is there already stays unless `replace`.
    Returns the voice ids taken over."""
    try:
        tar = tarfile.open(src, mode="r:gz")
    except (OSError, tarfile.TarError):
        raise VaultError("not a voices archive") from None
    voices.mkdir(parents=True, exist_ok=True)
    os.chmod(voices, 0o700)
    taken = []
    with tempfile.TemporaryDirectory(dir=voices.parent) as tmp, tar:
        tar.extractall(tmp, filter="data")   # no absolute paths, no "..", no links out
        for folder in sorted(Path(tmp).iterdir()):
            if not folder.is_dir():
                continue
            target = voices / folder.name
            if target.exists():
                if not replace:
                    continue
                shutil.rmtree(target)
            shutil.move(str(folder), target)
            taken.append(folder.name)
    return taken
