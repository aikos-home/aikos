"""Where the service keeps things. One state folder holds everything that must move to another machine: the voices, the
app's token, the settings, the heartbeat address. The cache and the models are made again on the new machine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def state_dir() -> Path:
    return Path(os.environ.get("AIKOS_TTS_STATE_DIR") or "~/.aikos/tts").expanduser()


def cache_dir() -> Path:
    if os.environ.get("AIKOS_TTS_CACHE_DIR"):
        return Path(os.environ["AIKOS_TTS_CACHE_DIR"]).expanduser()
    base = "~/Library/Caches" if sys.platform == "darwin" else os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return Path(base).expanduser() / "aikos" / "tts"


def secret_file(name: str, env: str) -> Path:
    """A file in the state folder (token, heartbeat-url) unless the environment names another one."""
    return Path(os.environ.get(env) or state_dir() / name).expanduser()
