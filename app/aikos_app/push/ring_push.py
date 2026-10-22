"""The push on every ring (A47, the owner: "Bei jedem Klingeln"): when `sensor.aikos_door_ring` gets a new time, everyone
who may act at the door gets a push; tapping it opens the door page with the live call. Ringing again within BURST_S is
the same ring (one push). Of the three nodes only the one that claims the ring first sends; a ring found after a restart
(older than FRESH_S) gets none.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ..ha.client import HaClient
from ..ha.door_call import RING
from ..roles import Cap, can
from ..store.accounts import Accounts
from ..store.push import Pushes
from .door_push import DoorPush

_LOGGER = logging.getLogger(__name__)
BURST_S = 30
FRESH_S = 60


def _time(iso: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


class RingPush:
    def __init__(self, ha: HaClient, accounts: Accounts, pushes: Pushes, door_push: DoorPush) -> None:
        self.ha, self.accounts, self.pushes, self.door_push = ha, accounts, pushes, door_push
        self._last: datetime | None = None
        self._burst: datetime | None = None
        self._tasks: set[asyncio.Task] = set()

    def attach(self) -> None:
        self.ha.on_change(self._on_change)

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()

    def _on_change(self, entity_id: str, state: dict[str, Any] | None) -> None:
        if entity_id != RING or not state:
            return
        t = _time(str(state.get("state") or ""))
        if t is None or (self._last is not None and t <= self._last):
            return
        new_burst = self._last is None or (t - self._last).total_seconds() >= BURST_S
        self._last = t
        if not new_burst:
            return   # ringing again: the same ring
        self._burst = t
        task = asyncio.get_running_loop().create_task(self._send(t))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, t: datetime) -> None:
        try:
            await self.notify(t)
        except Exception:
            _LOGGER.exception("ring push failed")

    async def notify(self, t: datetime) -> int:
        """Sends the push for one ring. Returns how many phones got it."""
        if (datetime.now(timezone.utc) - t).total_seconds() > FRESH_S:
            return 0
        iso = t.isoformat(timespec="seconds")
        if not self.pushes.claim(f"ring:{iso}"):
            return 0
        data = {"kind": "ring", "time": iso}
        sent = 0
        for user in self.accounts.list_users():
            if not user.disabled and can(user.role, Cap.DOOR_ACT):
                sent += await self.door_push.to_user(user.id, data, topic="ring")
        return sent
