"""Speech made ahead of time, one sentence after the other in the background (the model can only do one at a time).

Quick replies and announcements queue up. A draft (text still being typed in the app) goes first, because someone is about
to send it, and a newer draft of the same voice replaces the older one that hasn't started yet: only what is typed last
gets made. A made sentence lands in the engine's cache and plays at once when it is sent. A sentence whose check had to
wait too long (the shared Whisper busy with a long recording: the hub answers 503) is tried once more a little later;
nothing is ever said unchecked.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.error
from collections import deque
from pathlib import Path

from .engine import Engine

_LOGGER = logging.getLogger(__name__)
RETRY_S = 30


class Preparer:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._queue: deque[tuple[Path, str]] = deque()
        self._drafts: dict[str, tuple[Path, str]] = {}
        self._task: asyncio.Task | None = None
        self._retried: set[tuple[Path, str, str]] = set()

    def add(self, voice: str, ref: Path, texts: list[str], draft: bool = False) -> None:
        if draft:
            if texts:
                self._drafts[voice] = (ref, texts[-1])
        else:
            self._queue.extend((ref, t) for t in texts)
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    @property
    def pending(self) -> int:
        return len(self._queue) + len(self._drafts)

    def _next(self) -> tuple[Path, str] | None:
        if self._drafts:
            voice = next(iter(self._drafts))
            return self._drafts.pop(voice)
        return self._queue.popleft() if self._queue else None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while (job := self._next()) is not None:
            ref, text = job
            try:
                await loop.run_in_executor(None, self._engine.synthesize, text, ref)
            except urllib.error.HTTPError as e:
                if e.code == 503 and (ref, text, "retry") not in self._retried:
                    self._retried.add((ref, text, "retry"))
                    _LOGGER.info("check busy: one sentence tried again in %d s", RETRY_S)
                    loop.call_later(RETRY_S, lambda r=ref, t=text: self.add("", r, [t]))
                else:
                    _LOGGER.warning("not prepared: %s", e)
            except Exception as e:  # one sentence that can't be said must not stop the others
                _LOGGER.warning("not prepared: %s", e)

    async def idle(self) -> None:
        """For tests: until everything is made."""
        while self._task is not None and not self._task.done():
            await asyncio.sleep(0.01)
