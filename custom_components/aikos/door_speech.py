"""Speech at the door in a resident's own voice (aikos-app A42–A45, sprachausgabe S10): a text is made into a sound file
in Home Assistant's local media folder (`<media>/aikos/speech-<kind>-…`) through the configured TTS service, and played
through the door speaker. Used by the door actions (note, greeting) and the announcements.

Said on the spot (`say_now`), the door first plays its own short cue, then the text sentence by sentence: the first one
plays while the next is being made, so the visitor hears the voice after one sentence's time, not the whole text's. If a
sentence can't be said faithfully, the rest is not said either (the text is on the door's screen anyway).

The voice service or the door being away never breaks anything: then there is no file, or nothing is played.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import door_speaker, door_voice
from .const import OPT_TTS

_LOGGER = logging.getLogger(__name__)
FOLDER = "aikos"            # in Home Assistant's local media (not public)
PREFIX = "speech-"          # speech made in advance, next to the greeting sound
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(" ".join((text or "").split())) if s]


def write(path: Path, data: bytes, keep_prefix: str) -> None:
    """Write the file and remove the older ones of the same kind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in path.parent.glob(keep_prefix + "*"):
        if old.name != path.name:
            old.unlink(missing_ok=True)
    path.write_bytes(data)


def remove(folder: Path, prefix: str) -> None:
    if folder.is_dir():
        for old in folder.glob(prefix + "*"):
            old.unlink(missing_ok=True)


class DoorSpeech:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry

    def folder(self) -> Path | None:
        local = self._hass.config.media_dirs.get("local")
        return Path(local) / FOLDER if local else None

    def _engine(self) -> str:
        return str(self._entry.options.get(OPT_TTS) or "")

    async def make(self, text: str, voice: str, kind: str) -> str:
        """The text in that voice as a file (its name in the folder); "" without a voice service, voice or text, or if
        the service fails. A new file of a kind replaces the older one."""
        engine, folder = self._engine(), self.folder()
        if not (engine and voice and text and folder is not None):
            return ""
        try:
            ext, data = await door_voice.synthesize(self._hass, engine, text, voice)
        except Exception as e:  # the voice service being away must never break the door: the text is shown anyway
            _LOGGER.warning("aikos: no speech for the door: %s", e)
            return ""
        name = f"{PREFIX}{kind}-{secrets.token_hex(6)}.{ext.lstrip('.') or 'mp3'}"
        await self._hass.async_add_executor_job(write, folder / name, data, f"{PREFIX}{kind}-")
        return name

    async def play(self, name: str) -> bool:
        """Play a file of the folder at the door; False if it isn't there or the door doesn't take it."""
        folder = self.folder()
        if not name or folder is None:
            return False
        try:
            await door_speaker.play(self._hass, folder / name)
            return True
        except (door_speaker.DoorSpeakerError, OSError) as e:
            _LOGGER.warning("aikos: not played at the door: %s", e)
            return False

    async def drop(self, kind: str) -> None:
        """Remove the speech files of a kind."""
        folder = self.folder()
        if folder is not None:
            await self._hass.async_add_executor_job(remove, folder, f"{PREFIX}{kind}-")

    def can_speak(self, voice: str) -> bool:
        return bool(self._engine() and voice and self.folder() is not None)

    async def say_now(self, text: str, voice: str, kind: str = "now") -> bool:
        """A one-off text: the door's cue at once, then sentence after sentence, each played while the next is made;
        the files are removed afterwards. True if anything was played."""
        parts = sentences(text)
        if not (parts and self.can_speak(voice)):
            return False
        await door_speaker.cue(self._hass)
        made: asyncio.Queue[str] = asyncio.Queue()

        async def make_all() -> None:
            for i, s in enumerate(parts):
                name = await self.make(s, voice, f"{kind}-{i}")
                await made.put(name)
                if not name:   # not said faithfully: the rest isn't said either
                    return

        maker = self._hass.async_create_task(make_all(), eager_start=True)
        played = False
        try:
            for _ in parts:
                name = await made.get()
                if not name or not await self.play(name):
                    break
                played = True
        finally:
            maker.cancel()
            await asyncio.gather(maker, return_exceptions=True)
            await self.drop(kind)
        return played
