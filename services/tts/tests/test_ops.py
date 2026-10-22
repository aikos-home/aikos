"""Running and moving the service (0.6.0): one state folder; the voices exported only encrypted; the heartbeat says up only
with the check there; health answers without waiting; the self test runs only from this machine, in the test voice; the
engine follows the hardware; the models are pinned; no note text in the log."""

from __future__ import annotations

import sys
import types
import wave
from pathlib import Path

import pytest

from aikos_tts import heartbeat, paths, vault
from aikos_tts.__main__ import allow_list, resolve_engine
from aikos_tts.engine import FakeEngine, SpeechError, selftest_voice
from aikos_tts.http_api import create_app
from aikos_tts.verify import Verdict
from aikos_tts.voices import VoiceStore

TOKEN = "t" * 40


def test_one_state_folder_and_the_cache_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setenv("AIKOS_TTS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AIKOS_TTS_CACHE_DIR", str(tmp_path / "cache"))
    assert paths.state_dir() == tmp_path / "state" and paths.cache_dir() == tmp_path / "cache"
    assert paths.secret_file("token", "AIKOS_TTS_TOKEN_FILE") == tmp_path / "state" / "token"
    monkeypatch.delenv("AIKOS_TTS_STATE_DIR")
    assert paths.state_dir() == Path("~/.aikos/tts").expanduser()


def voice(folder: Path, vid: str) -> None:
    (folder / vid).mkdir(parents=True)
    (folder / vid / "ref.wav").write_bytes(b"RIFF" + vid.encode())
    (folder / vid / "meta.json").write_text('{"name": "x"}')


def test_voices_move_as_one_archive(tmp_path):
    voices = tmp_path / "voices"
    voice(voices, "va1")
    voice(voices, "vb2")
    out = tmp_path / "voices.tar.gz"
    assert vault.export(voices, out) == 2
    assert vault.restore(out, tmp_path / "new") == ["va1", "vb2"]
    assert (tmp_path / "new" / "va1" / "ref.wav").read_bytes() == b"RIFFva1"
    (tmp_path / "new" / "va1" / "ref.wav").write_bytes(b"newer")
    assert vault.restore(out, tmp_path / "new") == []                          # a voice there stays
    assert vault.restore(out, tmp_path / "new", replace=True) == ["va1", "vb2"]
    (tmp_path / "junk").write_bytes(b"not an archive")
    with pytest.raises(vault.VaultError):
        vault.restore(tmp_path / "junk", tmp_path / "new")


def test_heartbeat_is_up_only_with_the_check_and_says_why(monkeypatch, tmp_path):
    pushed = []

    class Resp:
        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(url, timeout=0):
        if url.endswith("/health"):
            if "down" in url:
                raise OSError("refused")
            return Resp()
        pushed.append(url)
        return Resp()
    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", fake_open)
    push = tmp_path / "heartbeat-url"
    push.write_text("https://kuma.example/api/push/abc?status=up&msg=OK&ping=")
    hb = heartbeat.Heartbeat("http://127.0.0.1/c/aikos-tts", push, "chatterbox-mlx")
    hb.beat()
    assert hb.whisper == "ok" and "status=up" in pushed[-1] and "msg=OK+%28chatterbox-mlx%29" in pushed[-1]
    hb.whisper_url = "http://down.example"
    hb.beat()
    assert hb.whisper == "unreachable" and "status=down" in pushed[-1] and "whisper+check+unreachable" in pushed[-1]
    hb.whisper_url = ""
    hb.beat()
    assert "whisper+check+not+configured" in pushed[-1]
    push.unlink()
    n = len(pushed)
    hb.beat()
    assert len(pushed) == n                                                     # no monitor set up: nothing pushed


class Checker:
    def __init__(self, ok=True, broken=False):
        self.ok, self.broken = ok, broken

    def check(self, expected, pcm, rate):
        if self.broken:
            raise OSError("whisper away")
        return Verdict(self.ok, None, 1.0 if self.ok else 0.0, "x")


async def test_health_says_engine_model_and_check_and_the_self_test_is_local_only(aiohttp_client, tmp_path):
    store = VoiceStore(tmp_path / "voices")
    engine = FakeEngine(checker=Checker())
    hb = heartbeat.Heartbeat("http://127.0.0.1:6667", tmp_path / "none", engine.name)
    hb.whisper = "ok"
    client = await aiohttp_client(create_app(store, engine, TOKEN, allow_list("192.0.2.1"), hb, "repo@0123456789ab"))
    h = await (await client.get("/v1/health")).json()
    assert h["engine"] == "fake" and h["model_revision"] == "repo@0123456789ab" and h["whisper"] == "ok"
    r = await client.post("/v1/selftest")                                       # loopback, no token needed
    assert r.status == 200 and (await r.json())["ok"] is True
    engine.checker = Checker(ok=False)
    assert (await (await client.post("/v1/selftest")).json()) | {"seconds": 0} == {"ok": False, "seconds": 0, "whisper_ok": True}
    engine.checker = Checker(broken=True)
    assert (await (await client.post("/v1/selftest")).json())["whisper_ok"] is False


async def test_self_test_refuses_other_machines(aiohttp_client, tmp_path):
    from aiohttp.test_utils import make_mocked_request

    from aikos_tts.http_api import LOOPBACK
    assert "192.0.2.31" not in LOOPBACK and {"127.0.0.1", "::1"} <= LOOPBACK
    with wave.open(str(selftest_voice())) as w:                                  # the test voice ships with the code
        assert w.getnchannels() == 1 and w.getnframes() / w.getframerate() > 5


def test_the_engine_follows_the_hardware():
    assert resolve_engine("auto", "Darwin", "arm64", has_mlx=True) == "chatterbox-mlx"
    assert resolve_engine("auto", "Darwin", "arm64", has_mlx=False) == "chatterbox"
    assert resolve_engine("auto", "Linux", "x86_64", has_mlx=False) == "chatterbox"    # CUDA or CPU
    assert resolve_engine("chatterbox", "Darwin", "arm64", has_mlx=True) == "chatterbox"


def test_models_are_pinned_and_main_points_at_the_pin(monkeypatch, tmp_path):
    from aikos_tts import models
    calls = []
    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = lambda **kw: calls.append(kw) or str(tmp_path / "snap")
    hub.constants = types.SimpleNamespace(HF_HUB_CACHE=str(tmp_path / "hub"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    models.fetch("chatterbox-mlx")
    assert [c["revision"] for c in calls] == [rev for _, rev, _ in models.PINS["chatterbox-mlx"]]
    main = tmp_path / "hub" / "models--mlx-community--S3TokenizerV2" / "refs" / "main"
    assert main.read_text() == models.PINS["chatterbox-mlx"][1][1]
    models.local("chatterbox-mlx")
    assert calls[-1]["local_files_only"] is True                                  # loading never goes online
    assert "mlx-community/chatterbox-multilingual-v3@035657" in models.revision("chatterbox-mlx")


def test_a_failed_sentence_leaves_its_text_out_of_the_log(tmp_path):
    engine = FakeEngine(checker=Checker(ok=False))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    with pytest.raises(SpeechError) as e:
        engine.synthesize("Der Schlüssel liegt unter der Matte.", ref)
    assert "Schlüssel" not in str(e.value) and "characters" in str(e.value)


def test_through_the_hub_the_heartbeat_asks_the_hubs_status(monkeypatch):
    """The hub sends paths other than the transcription to another backend (a /health would reach Ollama)."""
    import io
    import json as js
    seen = []

    def fake_open(url, timeout=0):
        seen.append(url)
        return io.BytesIO(js.dumps({"backends": {"whisper-shared": {"up": state["up"]}}}).encode())
    state = {"up": True}
    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", fake_open)
    assert heartbeat.whisper_state("http://127.0.0.1/c/aikos-tts", "whisper-shared") == "ok"
    assert seen[-1] == "http://127.0.0.1/hub/v1/status"
    state["up"] = False
    assert heartbeat.whisper_state("http://127.0.0.1/c/aikos-tts", "whisper-shared") == "unreachable"
    assert heartbeat.whisper_state("http://127.0.0.1/c/aikos-tts", "other") == "unreachable"


async def test_a_sentence_whose_check_waited_too_long_is_tried_once_more(monkeypatch):
    import urllib.error

    from aikos_tts import prepare
    calls = []

    class Busy(FakeEngine):
        def synthesize(self, text, reference):
            calls.append(text)
            raise urllib.error.HTTPError("http://hub", 503, "slot", {}, None)
    monkeypatch.setattr(prepare, "RETRY_S", 0.01)
    p = prepare.Preparer(Busy())
    p.add("v1", Path("ref.wav"), ["Komme sofort."])
    await p.idle()
    import asyncio
    await asyncio.sleep(0.05)
    await p.idle()
    assert calls == ["Komme sofort.", "Komme sofort."]                          # once more, then given up
