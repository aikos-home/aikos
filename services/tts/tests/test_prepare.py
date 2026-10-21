"""Speech made ahead of time: one after the other; a draft (being typed) goes first and only the newest draft of a voice
is made; a sentence that fails doesn't stop the others."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from aikos_tts.engine import FakeEngine
from aikos_tts.prepare import Preparer


class Recording(FakeEngine):
    def __init__(self):
        super().__init__()
        self.said: list[str] = []
        self.gate = threading.Event()

    def synthesize(self, text, reference):
        self.gate.wait(5)
        if text == "kaputt":
            raise RuntimeError("model away")
        self.said.append(text)
        return b""


async def test_drafts_go_first_and_only_the_newest_is_made():
    engine = Recording()
    p = Preparer(engine)
    ref = Path("ref.wav")
    p.add("v1", ref, ["Komme sofort.", "Moment bitte."])
    await asyncio.sleep(0.05)                                 # the first one has started and waits at the gate
    p.add("v1", ref, ["Ich bin"], draft=True)
    p.add("v1", ref, ["Ich bin gleich da."], draft=True)      # typed further before the older draft started
    p.add("v2", ref, ["Hallo."], draft=True)
    engine.gate.set()
    await p.idle()
    assert engine.said == ["Komme sofort.", "Ich bin gleich da.", "Hallo.", "Moment bitte."]
    assert p.pending == 0


async def test_a_sentence_that_fails_does_not_stop_the_others():
    engine = Recording()
    engine.gate.set()
    p = Preparer(engine)
    p.add("v1", Path("ref.wav"), ["kaputt", "Moment bitte."])
    await p.idle()
    assert engine.said == ["Moment bitte."]
