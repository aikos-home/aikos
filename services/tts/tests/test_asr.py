"""Speech to text for Home Assistant (SB-R4): the Whisper call, the caption filter, and the Wyoming side (transcribe, the
silent voice for devices without a speaker, off by default)."""

from __future__ import annotations

import asyncio
import email
import json
import socket
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.info import Describe, Info
from wyoming.server import AsyncServer
from wyoming.tts import Synthesize, SynthesizeVoice

from aikos_tts.__main__ import allow_list, make_recognizer
from aikos_tts.asr import MAX_S, Recognizer, clean
from aikos_tts.engine import FakeEngine
from aikos_tts.voices import VoiceStore
from aikos_tts.wyoming_handler import SILENT, Handler


@pytest.mark.parametrize("heard, kept", [
    (" Spiel Metal im Technikraum ab.\n", "Spiel Metal im Technikraum ab."),
    (" Vielen Dank für's Zuschauen.\n", ""),            # the remote's empty probe, 16.11.
    ("Vielen Dank fürs Zuschauen.", ""),
    ("Untertitel im Auftrag des ZDF für funk, 2017", ""),
    ("[Musik]", ""),
    ("*Klingeln*", ""),
    ("Pause. Vielen Dank fürs Zuschauen.", "Pause."),
    ("", ""),
])
def test_clean_drops_whisper_captions_and_keeps_commands(heard, kept):
    assert clean(heard) == kept


class Whisper(BaseHTTPRequestHandler):
    """Stands in for whisper-server: records the request, answers `text`."""
    seen: list[dict] = []
    answer = {"text": " Hallo Welt.\n"}

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        msg = email.message_from_bytes(f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + body)
        parts = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in msg.get_payload()}
        Whisper.seen.append({"path": self.path, **parts})
        out = json.dumps(Whisper.answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@pytest.fixture
def whisper():
    Whisper.seen = []
    server = HTTPServer(("127.0.0.1", 0), Whisper)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/c/aikos-tts"
    server.shutdown()


def test_recognizer_sends_german_wav_to_the_hub_path_and_cleans_the_text(whisper):
    text = Recognizer(whisper).transcribe(b"\x01\x00" * 16000, 16000)
    [req] = Whisper.seen
    assert text == "Hallo Welt."
    assert req["path"] == "/c/aikos-tts/v1/audio/transcriptions"
    assert (req["language"], req["response_format"], req["temperature"]) == (b"de", b"json", b"0")
    assert req["file"][:4] == b"RIFF" and len(req["file"]) == 44 + 2 * 16000


def test_recognizer_cuts_a_stuck_key_at_max_s(whisper):
    Recognizer(whisper).transcribe(b"\0\0" * 16000 * (MAX_S + 5), 16000)
    assert len(Whisper.seen[0]["file"]) == 44 + 2 * 16000 * MAX_S


def test_recognizer_is_off_unless_switched_on_with_a_whisper():
    url = "http://127.0.0.1/c/aikos-tts"
    assert make_recognizer({"AIKOS_TTS_WHISPER_URL": url}) is None                       # default: off
    assert make_recognizer({"AIKOS_TTS_STT": "1"}) is None                               # nothing to write with
    assert isinstance(make_recognizer({"AIKOS_TTS_STT": "1", "AIKOS_TTS_WHISPER_URL": url}), Recognizer)


class FakeRecognizer:
    def __init__(self, text="Fernseher Pause.", fail=False):
        self.text, self.fail, self.calls = text, fail, []

    def transcribe(self, pcm: bytes, rate: int) -> str:
        self.calls.append((len(pcm), rate))
        if self.fail:
            raise OSError("hub not there")
        return self.text


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def serve(tmp_path, recognizer, allowed="127.0.0.1"):
    port = free_port()
    engine = FakeEngine()
    server = AsyncServer.from_uri(f"tcp://127.0.0.1:{port}")
    task = asyncio.create_task(server.run(partial(Handler, store=VoiceStore(tmp_path / "voices"), engine=engine,
                                                  allowed=allow_list(allowed), recognizer=recognizer)))
    await asyncio.sleep(0.1)
    return port, task, engine


async def talk(port, events, until):
    out = []
    async with AsyncTcpClient("127.0.0.1", port) as c:
        for e in events:
            await c.write_event(e)
        while True:
            e = await asyncio.wait_for(c.read_event(), 5)
            if e is None:
                break
            out.append(e)
            if any(t.is_type(e.type) for t in until):
                break
    return out


def sentence(rate=16000, width=2, channels=1, seconds=1):
    audio = b"\x01\x00" * channels * (width // 2) * rate * seconds
    return [Transcribe(language="de").event(), AudioStart(rate=rate, width=width, channels=channels).event(),
            AudioChunk(rate=rate, width=width, channels=channels, audio=audio[: len(audio) // 2]).event(),
            AudioChunk(rate=rate, width=width, channels=channels, audio=audio[len(audio) // 2:]).event(),
            AudioStop().event()]


async def test_wyoming_writes_a_sentence_down(tmp_path):
    rec = FakeRecognizer()
    port, task, _ = await serve(tmp_path, rec)
    try:
        [info] = await talk(port, [Describe().event()], [Info])
        i = Info.from_event(info)
        assert [p.name for p in i.asr] == ["aikos-stt"] and i.asr[0].models[0].languages == ["de"]
        assert SILENT in [v.name for v in i.tts[0].voices]
        [out] = await talk(port, sentence(), [Transcript, Error])
        assert Transcript.from_event(out).text == "Fernseher Pause." and rec.calls == [(32000, 16000)]
    finally:
        task.cancel()


async def test_wyoming_refuses_what_it_cannot_write_down(tmp_path):
    port, task, _ = await serve(tmp_path, FakeRecognizer(fail=True))
    try:
        [err] = await talk(port, sentence(), [Transcript, Error])
        assert Error.from_event(err).code == "stt"                       # Whisper away: an error, never a made-up text
        [err] = await talk(port, sentence(channels=2), [Transcript, Error])
        assert Error.from_event(err).code == "stt-format"
    finally:
        task.cancel()


async def test_wyoming_refuses_machines_not_listed(tmp_path):
    rec = FakeRecognizer()
    port, task, _ = await serve(tmp_path, rec, allowed="192.0.2.238")
    try:
        [err] = await talk(port, sentence(), [Transcript, Error])
        assert Error.from_event(err).code == "forbidden" and rec.calls == []
    finally:
        task.cancel()


async def test_silent_voice_answers_at_once_without_the_model(tmp_path):
    port, task, engine = await serve(tmp_path, FakeRecognizer())
    try:
        events = await talk(port, [Synthesize(text="Ich habe Pause gedrückt.", voice=SynthesizeVoice(name=SILENT)).event()],
                            [AudioStop, Error])
        assert AudioStart.is_type(events[0].type) and AudioStop.is_type(events[-1].type)
        audio = b"".join(AudioChunk.from_event(e).audio for e in events if AudioChunk.is_type(e.type))
        assert audio and not any(audio) and engine.calls == []
    finally:
        task.cancel()


async def test_without_speech_to_text_nothing_changes(tmp_path):
    """Default (AIKOS_TTS_STT unset): no recognizer offered, no silent voice, a transcribe request is refused."""
    port, task, engine = await serve(tmp_path, None)
    try:
        [info] = await talk(port, [Describe().event()], [Info])
        i = Info.from_event(info)
        assert i.asr == [] and SILENT not in [v.name for v in i.tts[0].voices]
        [err] = await talk(port, sentence(), [Transcript, Error])
        assert Error.from_event(err).code == "stt"
        [err] = await talk(port, [Synthesize(text="x", voice=SynthesizeVoice(name=SILENT)).event()], [AudioStop, Error])
        assert Error.from_event(err).code == "voice" and engine.calls == []
    finally:
        task.cancel()
