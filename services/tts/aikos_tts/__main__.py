"""Run the service: Wyoming for Home Assistant and HTTP for the aikos app, in one process with one model.

    python -m aikos_tts --voices DIR [--wyoming tcp://0.0.0.0:10200] [--http 0.0.0.0:10201] [--engine chatterbox|fake]

Environment: AIKOS_TTS_TOKEN_FILE (the app's token), AIKOS_TTS_WYOMING_CLIENTS (Home Assistant addresses, comma-separated),
AIKOS_TTS_HTTP_CLIENTS (the app's nodes; an empty list allows nobody), AIKOS_TTS_WHISPER_URL (a local whisper-server that
checks every sentence against the text; empty = unchecked).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from functools import partial
from pathlib import Path

from aiohttp import web
from wyoming.server import AsyncServer

from .engine import ChatterboxEngine, Engine, FakeEngine
from .http_api import create_app
from .verify import WhisperChecker
from .voices import VoiceStore
from .wyoming_handler import Handler

_LOGGER = logging.getLogger("aikos_tts")


def allow_list(value: str):
    allowed = {a.strip() for a in (value or "").split(",") if a.strip()}
    return lambda addr: addr in allowed or (addr.startswith("::ffff:") and addr[7:] in allowed)


def make_engine(kind: str) -> Engine:
    url = os.environ.get("AIKOS_TTS_WHISPER_URL", "")
    checker = WhisperChecker(url) if url else None
    return FakeEngine(checker=checker) if kind == "fake" else ChatterboxEngine(checker=checker)


async def serve(args: argparse.Namespace) -> None:
    store = VoiceStore(Path(args.voices).expanduser())
    _LOGGER.info("loading the %s engine", args.engine)
    engine = await asyncio.get_running_loop().run_in_executor(None, make_engine, args.engine)
    token_file = os.environ.get("AIKOS_TTS_TOKEN_FILE", "")
    token = Path(token_file).expanduser().read_text(encoding="utf-8").strip() if token_file else ""
    app = create_app(store, engine, token, allow_list(os.environ.get("AIKOS_TTS_HTTP_CLIENTS", "")))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    host, port = args.http.rsplit(":", 1)
    await web.TCPSite(runner, host, int(port)).start()
    wy = AsyncServer.from_uri(args.wyoming)
    _LOGGER.info("ready: wyoming %s, http %s, %d voices, engine %s", args.wyoming, args.http, len(store.all()), engine.name)
    await wy.run(partial(Handler, store=store, engine=engine,
                         allowed=allow_list(os.environ.get("AIKOS_TTS_WYOMING_CLIENTS", ""))))


def main() -> None:
    p = argparse.ArgumentParser(prog="aikos_tts")
    p.add_argument("--voices", required=True)
    p.add_argument("--wyoming", default="tcp://0.0.0.0:10200")
    p.add_argument("--http", default="0.0.0.0:10201")
    p.add_argument("--engine", default="chatterbox", choices=["chatterbox", "fake"])
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
