"""Sentences already said play at once the next time; a new recording or a deleted voice never plays old takes."""

from __future__ import annotations

import asyncio
import os
import wave

from aikos_tts.cache import SpeechCache
from aikos_tts.engine import FakeEngine
from aikos_tts.http_api import create_app
from aikos_tts.voices import VoiceStore
from aikos_tts.__main__ import allow_list

TOKEN = "t" * 40


def fake_convert(src, dst):
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * 24000 * src.read_bytes()[0])


def setup(tmp_path):
    cache = SpeechCache(tmp_path / "cache")
    store = VoiceStore(tmp_path / "voices", convert=fake_convert, on_change=cache.drop)
    engine = FakeEngine()
    engine.cache = cache
    store.enrol("v1", "Alex", bytes([20]))
    return cache, store, engine


def test_the_same_sentence_is_made_once(tmp_path):
    cache, store, engine = setup(tmp_path)
    a = engine.synthesize("Komme sofort. Moment bitte.", store.reference("v1"))
    b = engine.synthesize("Moment bitte. Komme sofort.", store.reference("v1"))     # same sentences, other order
    assert [t for t, _ in engine.calls] == ["Komme sofort.", "Moment bitte."] and len(a) == len(b)
    assert cache.count("v1") == 2


def test_a_new_recording_never_plays_old_takes(tmp_path):
    cache, store, engine = setup(tmp_path)
    engine.synthesize("Komme sofort.", store.reference("v1"))
    store.enrol("v1", "Alex", bytes([22]))
    os.utime(store.reference("v1"), (1, 1))                                        # another recording time
    engine.synthesize("Komme sofort.", store.reference("v1"))
    assert len(engine.calls) == 2
    store.delete("v1")
    assert cache.count("v1") == 0


async def test_prepare_says_them_in_the_background(aiohttp_client, tmp_path):
    cache, store, engine = setup(tmp_path)
    client = await aiohttp_client(create_app(store, engine, TOKEN, allow_list("127.0.0.1")))
    r = await client.post("/v1/prepare", json={"voice": "v1", "texts": ["Komme sofort.", "x" * 400, "Moment bitte."]},
                          headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status == 202 and (await r.json())["queued"] == 2                     # the too-long one is left out
    for _ in range(100):
        if cache.count("v1") == 2:
            break
        await asyncio.sleep(0.02)
    assert cache.count("v1") == 2
    assert (await client.post("/v1/prepare", json={"voice": "nope", "texts": ["x"]},
                              headers={"Authorization": f"Bearer {TOKEN}"})).status == 404


def test_another_model_never_plays_this_ones_takes(tmp_path):
    cache = SpeechCache(tmp_path / "cache")
    cache.put("v1", 1.0, "Komme sofort.", 24000, b"\x01\x00", "chatterbox")
    assert cache.get("v1", 1.0, "Komme sofort.", 24000, "chatterbox") == b"\x01\x00"
    assert cache.get("v1", 1.0, "Komme sofort.", 24000, "chatterbox-mlx") is None


def test_a_take_made_while_typing_fits_the_sentence_with_its_full_stop(tmp_path):
    cache = SpeechCache(tmp_path / "cache")
    cache.put("v1", 1.0, "Ich komme gleich", 24000, b"\x01\x00", "m")
    assert cache.get("v1", 1.0, "Ich komme gleich!", 24000, "m") == b"\x01\x00"
    assert cache.get("v1", 1.0, "Ich komme gleich.", 24000, "m") == b"\x01\x00"
    assert cache.get("v1", 1.0, "Ich komme gleich nicht", 24000, "m") is None
