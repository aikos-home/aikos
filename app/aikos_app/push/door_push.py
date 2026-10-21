"""The push for a new door message (rules A15, A24, G5): sees the register's `newest` change in Home Assistant, waits for
the last words, and sends title data, speaker and recognised text, never sound, to the phones of the people who may see
that message. Of the three nodes only the one that claims the message first sends.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ..api.people_view import door_names
from ..ha.client import HaClient, HaError
from ..ha.door import REGISTER_ENTITY, DoorMessage, DoorMessages
from ..roles import may_see_message
from ..store.accounts import Accounts
from ..store.push import Pushes
from .sender import PushSender

_LOGGER = logging.getLogger(__name__)
WAIT_FOR_WORDS_S = 6   # the last words are transcribed a few seconds after the message was saved
FRESH_S = 600          # an older message (e.g. found after a restart) gets no push
TEXT_MAX = 500


def payload(m: DoorMessage, someone_here: bool | None) -> dict[str, Any]:
    """What the phone's service worker turns into the notification (it formats time and text in the phone's language)."""
    return {"kind": "door_message", "id": m.id, "time": m.time, "seconds": m.seconds, "recipient": m.recipient,
            "speaker": m.speaker, "text": m.text[:TEXT_MAX], "here": someone_here}


def _age_s(iso: str) -> float:
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return float("inf")
    if t.tzinfo is None:
        return float("inf")
    return (datetime.now(timezone.utc) - t).total_seconds()


class DoorPush:
    def __init__(self, ha: HaClient, door: DoorMessages, accounts: Accounts, pushes: Pushes, sender: PushSender,
                 someone_entity: str) -> None:
        self.ha, self.door, self.accounts, self.pushes, self.sender = ha, door, accounts, pushes, sender
        self.someone_entity = someone_entity
        self._newest = ""
        self._tasks: set[asyncio.Task] = set()

    def attach(self) -> None:
        self.ha.on_change(self._on_change)

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()

    def _on_change(self, entity_id: str, state: dict[str, Any] | None) -> None:
        if entity_id != REGISTER_ENTITY or not state:
            return
        newest = str((state.get("attributes") or {}).get("newest") or "")
        if not newest or newest == self._newest:
            return
        self._newest = newest
        task = asyncio.get_running_loop().create_task(self._later(newest))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _later(self, message_id: str) -> None:
        await asyncio.sleep(WAIT_FOR_WORDS_S)
        try:
            await self.notify(message_id)
        except HaError as e:
            _LOGGER.warning("door push for %s: %s", message_id, e)
        except Exception:
            _LOGGER.exception("door push for %s failed", message_id)

    async def notify(self, message_id: str) -> int:
        """Sends the push for one message. Returns how many phones got it."""
        m = next((x for x in await self.door.list() if x.id == message_id), None)
        if m is None or _age_s(m.time) > FRESH_S or not self.pushes.claim(f"door:{m.id}"):
            return 0
        st = self.ha.state(self.someone_entity) if self.someone_entity else None
        here = None if not st or st.get("state") in (None, "unknown", "unavailable") else st.get("state") == "on"
        data = payload(m, here)
        sent = 0
        for user in self.accounts.list_users():
            if user.disabled or not may_see_message(user.role, door_names(user), m.recipient):
                continue
            sent += await self.to_user(user.id, data, topic=m.id[-32:])
        return sent

    async def to_user(self, user_id: int, data: dict[str, Any], topic: str = "") -> int:
        sent = 0
        for sub in self.pushes.of_user(user_id):
            result = await self.sender.send(sub.endpoint, sub.p256dh, sub.auth, data, topic=topic)
            if result == "ok":
                self.pushes.delivered(sub.endpoint)
                sent += 1
            elif result == "gone":
                self.pushes.gone(sub.endpoint)
        return sent
