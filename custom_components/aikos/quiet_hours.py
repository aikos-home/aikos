"""Quiet hours as pure time logic: is a moment inside the window, and when does that next change.

No Home Assistant imports, so the rules can be tested and reused on their own.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta


def is_quiet(now: time, start: time, end: time) -> bool:
    """True from `start` (inclusive) to `end` (exclusive); the window may run over midnight. `start == end` is an empty window."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def next_change(now: datetime, start: time, end: time) -> datetime | None:
    """The first moment after `now` at which `start` or `end` is reached, in `now`'s time zone; None for an empty window."""
    if start == end:
        return None
    candidates = []
    for days in (0, 1):
        day = (now + timedelta(days=days)).date()
        for boundary in (start, end):
            moment = datetime.combine(day, boundary, tzinfo=now.tzinfo)
            if moment > now:
                candidates.append(moment)
    return min(candidates)
