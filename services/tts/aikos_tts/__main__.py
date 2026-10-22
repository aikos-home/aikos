"""Run the service: Wyoming for Home Assistant and HTTP for the aikos app, in one process with one model.

    python -m aikos_tts [serve] [--engine auto|chatterbox|chatterbox-mlx|fake] [--wyoming tcp://0.0.0.0:10200]
                        [--http 0.0.0.0:10201]
    python -m aikos_tts fetch --engine ENGINE        (the pinned model files, online, once; models.py)
    python -m aikos_tts export FILE                  (the voices as one archive, to move them; vault.py)
    python -m aikos_tts import FILE [--replace]

Everything that must move to another machine is in the state folder (AIKOS_TTS_STATE_DIR, default ~/.aikos/tts): voices/,
token (the app's), heartbeat-url (the monitor's push address), tts.env (read by the installer). The cache is elsewhere
(AIKOS_TTS_CACHE_DIR, made again). Environment: AIKOS_TTS_WYOMING_CLIENTS (Home Assistant addresses, comma-separated),
AIKOS_TTS_HTTP_CLIENTS (the app's nodes; an empty list allows nobody), AIKOS_TTS_WHISPER_URL (the Whisper that checks every
sentence; empty = unchecked, and the heartbeat says so), AIKOS_TTS_TOKEN_FILE / AIKOS_TTS_HEARTBEAT_FILE (other places for
those files).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import os
import platform
from functools import partial
from pathlib import Path

from .cache import SpeechCache
from .engine import ChatterboxEngine, Engine, FakeEngine, MlxChatterboxEngine
from .verify import WhisperChecker
from .voices import VoiceStore

_LOGGER = logging.getLogger("aikos_tts")
ENGINES = ["auto", "chatterbox", "chatterbox-mlx", "fake"]


def allow_list(value: str):
    allowed = {a.strip() for a in (value or "").split(",") if a.strip()}
    return lambda addr: addr in allowed or (addr.startswith("::ffff:") and addr[7:] in allowed)


def resolve_engine(kind: str, system: str = "", machine: str = "", has_mlx: bool | None = None) -> str:
    """`auto`: MLX on Apple silicon (where mlx-audio is installed), else the PyTorch engine (CUDA, MPS or CPU)."""
    if kind != "auto":
        return kind
    system, machine = system or platform.system(), machine or platform.machine()
    if has_mlx is None:
        has_mlx = importlib.util.find_spec("mlx_audio") is not None
    return "chatterbox-mlx" if (system, machine) == ("Darwin", "arm64") and has_mlx else "chatterbox"


def make_engine(kind: str) -> Engine:
    url = os.environ.get("AIKOS_TTS_WHISPER_URL", "")
    checker = WhisperChecker(url) if url else None
    if kind == "fake":
        return FakeEngine(checker=checker)
    return MlxChatterboxEngine(checker=checker) if kind == "chatterbox-mlx" else ChatterboxEngine(checker=checker)


async def serve(args: argparse.Namespace) -> None:
    from aiohttp import web
    from wyoming.server import AsyncServer

    from . import models, paths
    from .heartbeat import Heartbeat
    from .http_api import create_app
    from .wyoming_handler import Handler

    kind = resolve_engine(args.engine)
    cache = SpeechCache(paths.cache_dir())
    store = VoiceStore(paths.state_dir() / "voices", on_change=cache.drop)
    _LOGGER.info("loading the %s engine", kind)
    engine = await asyncio.get_running_loop().run_in_executor(None, make_engine, kind)
    engine.cache = cache
    voices = store.all()
    if voices and kind != "fake":
        try:
            await asyncio.get_running_loop().run_in_executor(None, engine.warm_up, store.reference(voices[0].id))
        except Exception as e:  # warming up is a nicety; the service runs without it
            _LOGGER.warning("not warmed up: %s", e)
    token_file = paths.secret_file("token", "AIKOS_TTS_TOKEN_FILE")
    token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else ""
    heartbeat = Heartbeat(os.environ.get("AIKOS_TTS_WHISPER_URL", ""),
                          paths.secret_file("heartbeat-url", "AIKOS_TTS_HEARTBEAT_FILE"), engine.name)
    app = create_app(store, engine, token, allow_list(os.environ.get("AIKOS_TTS_HTTP_CLIENTS", "")), heartbeat,
                     models.revision(kind))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    host, port = args.http.rsplit(":", 1)
    await web.TCPSite(runner, host, int(port)).start()
    beating = asyncio.get_running_loop().create_task(heartbeat.run())
    wy = AsyncServer.from_uri(args.wyoming)
    _LOGGER.info("ready: wyoming %s, http %s, %d voices, engine %s", args.wyoming, args.http, len(store.all()), engine.name)
    try:
        await wy.run(partial(Handler, store=store, engine=engine,
                             allowed=allow_list(os.environ.get("AIKOS_TTS_WYOMING_CLIENTS", ""))))
    finally:
        beating.cancel()


def main() -> None:
    p = argparse.ArgumentParser(prog="aikos_tts")
    sub = p.add_subparsers(dest="command")
    for name in ("serve", None):
        q = sub.add_parser("serve") if name else p
        q.add_argument("--engine", default="auto", choices=ENGINES)
        q.add_argument("--wyoming", default="tcp://0.0.0.0:10200")
        q.add_argument("--http", default="0.0.0.0:10201")
    f = sub.add_parser("fetch")
    f.add_argument("--engine", default="auto", choices=ENGINES)
    e = sub.add_parser("export")
    e.add_argument("file")
    i = sub.add_parser("import")
    i.add_argument("file")
    i.add_argument("--replace", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from . import models, paths, vault
    if args.command == "fetch":
        kind = resolve_engine(args.engine)
        if kind != "fake":
            for folder in models.fetch(kind):
                print(folder)
    elif args.command == "export":
        n = vault.export(paths.state_dir() / "voices", Path(args.file))
        print(f"{n} voices exported to {args.file}")
    elif args.command == "import":
        taken = vault.restore(Path(args.file), paths.state_dir() / "voices", args.replace)
        print(f"{len(taken)} voices imported: {', '.join(taken) or '-'}")
    else:
        asyncio.run(serve(args))


if __name__ == "__main__":
    main()
