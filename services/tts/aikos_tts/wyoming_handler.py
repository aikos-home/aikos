"""Home Assistant's side: the Wyoming protocol (its standard link to a TTS service). Each enrolled person is a voice; the
voice name in `synthesize` picks whose. Only the listed Home Assistant machines may ask: a cloned voice must not be
something anyone in the network can fetch.

With a recognizer (AIKOS_TTS_STT, off by default) the same link also writes speech down (`transcribe` + audio → `transcript`,
asr.py) and offers the voice `aikos-silent`: an ESPHome device always asks its pipeline for a spoken answer, also one
without a speaker, and that answer must not take the one slot the residents' voices share (SB-R4).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info, TtsProgram, TtsVoice
from wyoming.server import AsyncEventHandler
from wyoming.tts import Synthesize

from . import __version__
from .asr import MAX_S, Recognizer
from .engine import Engine
from .voices import VoiceStore

_LOGGER = logging.getLogger(__name__)
CHUNK = 4096
TEXT_MAX = 600
ATTRIBUTION = Attribution(name="aikos-home", url="https://github.com/aikos-home/aikos")
SILENT = "aikos-silent"     # the answer for a device without a speaker: a moment of silence, at once, without the model
SILENT_RATE = 16000


def info(store: VoiceStore, engine: Engine, stt: bool = False) -> Info:
    voices = [TtsVoice(name=v.id, description=v.name, attribution=ATTRIBUTION, installed=True, version=None,
                       languages=["de"]) for v in store.all()]
    asr: list[AsrProgram] = []
    if stt:
        voices.append(TtsVoice(name=SILENT, description="Ohne Ton (Geräte ohne Lautsprecher)", attribution=ATTRIBUTION,
                               installed=True, version=None, languages=["de"]))
        asr = [AsrProgram(name="aikos-stt", description="aikos speech to text (Whisper through the aikos hub)",
                          attribution=ATTRIBUTION, installed=True, version=__version__,
                          models=[AsrModel(name="whisper", description="Whisper large-v3 (aikos hub)", attribution=ATTRIBUTION,
                                           installed=True, version=None, languages=["de"])])]
    return Info(tts=[TtsProgram(name="aikos-tts", description=f"aikos TTS ({engine.name})", attribution=ATTRIBUTION,
                                installed=True, version=__version__, voices=voices)], asr=asr)


class Handler(AsyncEventHandler):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, store: VoiceStore, engine: Engine,
                 allowed: Callable[[str], bool], recognizer: Recognizer | None = None) -> None:
        super().__init__(reader, writer)
        self.store, self.engine, self.recognizer = store, engine, recognizer
        self.audio, self.rate, self.listening, self.mono16 = bytearray(), SILENT_RATE, False, True
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
            await self.write_event(info(self.store, self.engine, self.recognizer is not None).event())
            return True
        if Synthesize.is_type(event.type):
            await self._synthesize(Synthesize.from_event(event))
            return True
        if any(t.is_type(event.type) for t in (Transcribe, AudioStart, AudioChunk, AudioStop)):
            return await self._hear(event)
        return True

    async def _hear(self, event: Event) -> bool:
        """transcribe → audio-start → audio-chunk … → audio-stop: the recording is written down once it is complete."""
        if self.recognizer is None:             # as before 0.7.0: audio from a client is ignored, only a request is refused
            if Transcribe.is_type(event.type):
                await self.write_event(Error(text="speech to text is off", code="stt").event())
                return False
            return True
        if Transcribe.is_type(event.type):
            self.audio, self.listening, self.mono16 = bytearray(), True, True
        elif AudioStart.is_type(event.type):
            start = AudioStart.from_event(event)
            self.audio, self.listening, self.rate = bytearray(), True, start.rate
            self.mono16 = (start.width, start.channels) == (2, 1)
        elif AudioChunk.is_type(event.type) and self.listening:
            chunk = AudioChunk.from_event(event)
            self.rate = chunk.rate
            self.mono16 = self.mono16 and (chunk.width, chunk.channels) == (2, 1)
            if len(self.audio) < MAX_S * self.rate * 2:
                self.audio += chunk.audio
        elif AudioStop.is_type(event.type) and self.listening:
            self.listening = False
            await self._transcribe(bytes(self.audio), self.rate)
        return True

    async def _transcribe(self, pcm: bytes, rate: int) -> None:
        if not self.mono16:
            await self.write_event(Error(text="only 16-bit mono audio", code="stt-format").event())
            return
        try:
            text = await asyncio.get_running_loop().run_in_executor(None, self.recognizer.transcribe, pcm, rate)
        except Exception as e:  # Whisper or the hub not there, or busy too long: nothing written down
            _LOGGER.warning("not written down for %s: %s", self.peer, e)
            await self.write_event(Error(text="could not write it down", code="stt").event())
            return
        await self.write_event(Transcript(text=text).event())
        _LOGGER.info("wrote down %.1f s for %s: %d characters", len(pcm) / 2 / max(1, rate), self.peer, len(text))

    async def _silence(self) -> None:
        await self.write_event(AudioStart(rate=SILENT_RATE, width=2, channels=1).event())
        await self.write_event(AudioChunk(rate=SILENT_RATE, width=2, channels=1, audio=bytes(SILENT_RATE // 5)).event())
        await self.write_event(AudioStop().event())

    async def _synthesize(self, s: Synthesize) -> None:
        voice_id = (s.voice.name if s.voice else "") or ""
        if voice_id == SILENT and self.recognizer is not None:
            await self._silence()
            return
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
