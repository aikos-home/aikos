"""Home Assistant's side: the Wyoming protocol (its standard link to a TTS service). Each enrolled person is a voice; the
voice name in `synthesize` picks whose. Only the listed Home Assistant machines may ask: a cloned voice must not be
something anyone in the network can fetch.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, TtsProgram, TtsVoice
from wyoming.server import AsyncEventHandler
from wyoming.tts import Synthesize

from . import __version__
from .engine import Engine
from .voices import VoiceStore

_LOGGER = logging.getLogger(__name__)
CHUNK = 4096
TEXT_MAX = 600
ATTRIBUTION = Attribution(name="aikos-home", url="https://github.com/aikos-home/aikos")


def info(store: VoiceStore, engine: Engine) -> Info:
    voices = [TtsVoice(name=v.id, description=v.name, attribution=ATTRIBUTION, installed=True, version=None,
                       languages=["de"]) for v in store.all()]
    return Info(tts=[TtsProgram(name="aikos-tts", description=f"aikos TTS ({engine.name})", attribution=ATTRIBUTION,
                                installed=True, version=__version__, voices=voices)])


class Handler(AsyncEventHandler):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, store: VoiceStore, engine: Engine,
                 allowed: Callable[[str], bool]) -> None:
        super().__init__(reader, writer)
        self.store, self.engine = store, engine
        peer = writer.get_extra_info("peername") or ("", 0)
        self.peer = str(peer[0])
        self.ok = allowed(self.peer)
        if not self.ok:
            _LOGGER.warning("refused Wyoming client %s", self.peer)

    async def handle_event(self, event: Event) -> bool:
        if not self.ok:
            await self.write_event(Error(text="not allowed", code="forbidden").event())
            return False
        if Describe.is_type(event.type):
            await self.write_event(info(self.store, self.engine).event())
            return True
        if Synthesize.is_type(event.type):
            await self._synthesize(Synthesize.from_event(event))
            return True
        return True

    async def _synthesize(self, s: Synthesize) -> None:
        voice_id = (s.voice.name if s.voice else "") or ""
        ref = self.store.reference(voice_id) if voice_id else None
        if ref is None:
            await self.write_event(Error(text=f"unknown voice {voice_id!r}", code="voice").event())
            return
        text = " ".join((s.text or "").split())[:TEXT_MAX]
        try:
            pcm = await asyncio.get_running_loop().run_in_executor(None, self.engine.synthesize, text, ref)
        except Exception as e:  # the text could not be said faithfully (or the model failed): say nothing
            _LOGGER.warning("not spoken for %s: %s", self.peer, e, exc_info=not isinstance(e, RuntimeError))
            await self.write_event(Error(text="could not say it", code="speech").event())
            return
        rate = self.engine.rate
        await self.write_event(AudioStart(rate=rate, width=2, channels=1).event())
        for i in range(0, len(pcm), CHUNK):
            await self.write_event(AudioChunk(rate=rate, width=2, channels=1, audio=pcm[i:i + CHUNK]).event())
        await self.write_event(AudioStop().event())
        _LOGGER.info("spoke %d characters as %s for %s", len(text), voice_id, self.peer)
