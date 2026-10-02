"""Writes the call archive (R23) to <config>/aikos_archive/calls.jsonl when the option is on.

Python appends the lines itself; no shell is involved, so visitor text can never become a command. Lines are written in the
order the events happen (one writer task, file access in the executor).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from . import call_archive
from .const import LIVE_CALL, MANUFACTURER, OPT_ARCHIVE, TEST_CALL

_LOGGER = logging.getLogger(__name__)
EVENTS = {"aikos_talk_transcript": False, "aikos_talk_transcript_test": True}


def _append(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("".join(line + "\n" for line in lines))


class ArchiveWriter:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self.path = Path(hass.config.path("aikos_archive", "calls.jsonl"))
        self._unsubs: list[Callable[[], None]] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    @callback
    def start(self) -> None:
        """Follow the option: on = listen and write, off = stop."""
        enabled = bool(self._entry.options.get(OPT_ARCHIVE, False))
        if enabled and not self._unsubs:
            self._unsubs.append(async_track_state_change_event(self._hass, [LIVE_CALL, TEST_CALL], self._on_call))
            for event_type in EVENTS:
                self._unsubs.append(self._hass.bus.async_listen(event_type, self._on_transcript))
            self._task = self._entry.async_create_background_task(self._hass, self._write_loop(), "aikos call archive")
        elif not enabled:
            self.stop()

    @callback
    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _write_loop(self) -> None:
        while True:
            lines = [await self._queue.get()]
            while not self._queue.empty():
                lines.append(self._queue.get_nowait())
            try:
                await self._hass.async_add_executor_job(_append, self.path, lines)
            except OSError:
                _LOGGER.exception("aikos: call archive %s not writable", self.path)
            finally:
                for _ in lines:
                    self._queue.task_done()

    async def async_flush(self) -> None:
        """Wait until every line handed over so far is on disk."""
        await self._queue.join()

    def _devices(self) -> list[dict[str, str | None]]:
        return [{"name": d.name_by_user or d.name, "model": d.model, "sw": d.sw_version}
                for d in dr.async_get(self._hass).devices if d.manufacturer == MANUFACTURER]  # iterate, no mapping use (HA 2026.9)

    @callback
    def _on_call(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if old is None or new is None:
            return
        test = event.data["entity_id"] == TEST_CALL
        now = dt_util.now()
        if old.state == "off" and new.state == "on":
            self._queue.put_nowait(call_archive.call_start(now, test, new.last_changed.isoformat(timespec="seconds"), self._devices()))
        elif old.state == "on" and new.state == "off":
            duration = (new.last_changed - old.last_changed).total_seconds()
            self._queue.put_nowait(call_archive.call_end(now, test, old.last_changed.isoformat(timespec="seconds"), duration))

    @callback
    def _on_transcript(self, event: Event) -> None:
        test = EVENTS[event.event_type]
        call = self._hass.states.get(TEST_CALL if test else LIVE_CALL)
        running = call is not None and call.state == "on"
        call_id = call.last_changed.isoformat(timespec="seconds") if running else ""
        self._queue.put_nowait(call_archive.message(dt_util.now(), test, call_id, running, event.data))
