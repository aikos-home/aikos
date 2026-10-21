"""aikos TTS without the real model: voices on disk, the app's HTTP API (token, addresses), Home Assistant's Wyoming side
(only the listed machines, voice by name), sentence splitting."""

from __future__ import annotations

import asyncio
import socket
import wave
from functools import partial
from pathlib import Path

import pytest
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.info import Describe, Info
from wyoming.server import AsyncServer
from wyoming.tts import Synthesize, SynthesizeVoice

from aikos_tts.__main__ import allow_list
from aikos_tts.engine import FakeEngine, sentences
from aikos_tts.http_api import create_app
from aikos_tts.voices import VoiceError, VoiceStore
from aikos_tts.wyoming_handler import Handler

TOKEN = "t" * 40


def fake_convert(src: Path, dst: Path) -> None:
    """Stands in for ffmpeg: the upload's first byte says how many seconds the "recording" is."""
    seconds = src.read_bytes()[0]
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * 24000 * seconds)


@pytest.fixture
def store(tmp_path):
    return VoiceStore(tmp_path / "voices", convert=fake_convert)


def test_sentences_split_long_notes_and_keep_short_ones():
    assert sentences("  Komme sofort.  ") == ["Komme sofort."]
    assert sentences("Hallo! Ich komme gleich. Bitte warten?") == ["Hallo!", "Ich komme gleich.", "Bitte warten?"]
    long = ", ".join(["ein recht langer Satzteil"] * 20) + "."
    parts = sentences(long)
    assert all(len(p) <= 221 for p in parts) and " ".join(parts).replace("  ", " ") == long
    assert sentences("   ") == []


def test_voice_store_enrol_replace_delete(store):
    with pytest.raises(VoiceError, match="too short"):
        store.enrol("u1", "Alex", bytes([5]))
    v = store.enrol("u1", "  Alex  ", bytes([20]))
    assert (v.id, v.name, round(v.seconds)) == ("u1", "Alex", 20)
    assert store.reference("u1").is_file() and [x.id for x in store.all()] == ["u1"]
    store.enrol("u1", "Alex", bytes([25]))                                   # replaced
    assert round(store.get("u1").seconds) == 25
    with pytest.raises(VoiceError, match="too short"):
        store.enrol("u1", "Alex", bytes([3]))
    assert round(store.get("u1").seconds) == 25                              # a failed new recording keeps the old one
    for bad in ("../x", "U1", "", "a" * 41, "x/y"):
        with pytest.raises(VoiceError):
            store.enrol(bad, "x", bytes([20]))
    assert store.delete("u1") and store.get("u1") is None and not store.delete("u1")


@pytest.fixture
async def api(aiohttp_client, store):
    engine = FakeEngine()
    client = await aiohttp_client(create_app(store, engine, TOKEN, allow_list("127.0.0.1")))
    client.engine = engine
    return client


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


async def test_http_needs_the_token(api):
    assert (await api.get("/v1/health")).status == 200                        # health only: no secrets in it
    assert (await api.get("/v1/voices")).status == 401
    assert (await api.get("/v1/voices", headers=auth("wrong"))).status == 401
    assert (await api.get("/v1/voices", headers=auth())).status == 200


async def test_http_refuses_other_addresses(aiohttp_client, store):
    client = await aiohttp_client(create_app(store, FakeEngine(), TOKEN, allow_list("192.0.2.31,192.0.2.32")))
    r = await client.get("/v1/voices", headers=auth())
    assert r.status == 403


async def test_http_enrol_speak_delete(api):
    r = await api.put("/v1/voices/u1", data=bytes([20]), headers={**auth(), "X-Voice-Name": "Alex%20K"})
    assert r.status == 200 and (await r.json())["name"] == "Alex K"
    r = await api.put("/v1/voices/u2", data=bytes([4]), headers=auth())
    assert r.status == 400 and "too short" in (await r.json())["error"]
    assert [v["id"] for v in await (await api.get("/v1/voices", headers=auth())).json()] == ["u1"]
    r = await api.post("/v1/speak", json={"voice": "u1", "text": "Komme sofort."}, headers=auth())
    assert r.status == 200 and r.content_type == "audio/wav" and (await r.read())[:4] == b"RIFF"
    assert api.engine.calls == [("Komme sofort.", "u1")]
    assert (await api.post("/v1/speak", json={"voice": "u9", "text": "x"}, headers=auth())).status == 404
    assert (await api.post("/v1/speak", json={"voice": "u1", "text": "x" * 301}, headers=auth())).status == 400
    assert (await api.delete("/v1/voices/u1", headers=auth())).status == 204
    assert (await api.delete("/v1/voices/u1", headers=auth())).status == 404


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def wyoming_server(store, engine, allowed):
    port = free_port()
    server = AsyncServer.from_uri(f"tcp://127.0.0.1:{port}")
    task = asyncio.create_task(server.run(partial(Handler, store=store, engine=engine, allowed=allow_list(allowed))))
    await asyncio.sleep(0.1)
    return port, task


async def ask(port, event):
    out = []
    async with AsyncTcpClient("127.0.0.1", port) as c:
        await c.write_event(event)
        while True:
            e = await asyncio.wait_for(c.read_event(), 5)
            if e is None:
                break
            out.append(e)
            if Info.is_type(e.type) or AudioStop.is_type(e.type) or Error.is_type(e.type):
                break
    return out


async def test_wyoming_lists_voices_and_speaks_by_voice_name(store):
    store.enrol("u1", "Alex", bytes([20]))
    engine = FakeEngine()
    port, task = await wyoming_server(store, engine, "127.0.0.1")
    try:
        [info] = await ask(port, Describe().event())
        voices = Info.from_event(info).tts[0].voices
        assert [(v.name, v.description, v.languages) for v in voices] == [("u1", "Alex", ["de"])]
        events = await ask(port, Synthesize(text="Moment bitte.", voice=SynthesizeVoice(name="u1")).event())
        assert AudioStart.is_type(events[0].type) and AudioStop.is_type(events[-1].type)
        audio = b"".join(AudioChunk.from_event(e).audio for e in events if AudioChunk.is_type(e.type))
        assert len(audio) == 2 * int(16000 * 0.02 * len("Moment bitte."))
        [err] = await ask(port, Synthesize(text="x", voice=SynthesizeVoice(name="u9")).event())
        assert Error.is_type(err.type)
        [err] = await ask(port, Synthesize(text="x").event())                 # no voice: nothing in anyone's voice
        assert Error.is_type(err.type) and engine.calls == [("Moment bitte.", "u1")]
    finally:
        task.cancel()


async def test_wyoming_refuses_machines_not_listed(store):
    store.enrol("u1", "Alex", bytes([20]))
    engine = FakeEngine()
    port, task = await wyoming_server(store, engine, "192.0.2.238")
    try:
        [err] = await ask(port, Synthesize(text="Hallo", voice=SynthesizeVoice(name="u1")).event())
        assert Error.is_type(err.type) and engine.calls == []
    finally:
        task.cancel()
