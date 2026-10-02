"""When a ring becomes a push to the residents' phones, and what it says. No Home Assistant imports."""
from __future__ import annotations

from datetime import datetime, timedelta

# Storm ringing (holding the button) and quick repeats give one push, not one per press.
MIN_GAP = timedelta(seconds=30)

QUIET_HOURS = "quiet_hours"
NOBODY_HOME = "nobody_home"

_TEXT = {
    "de": {"ring": "Es hat geklingelt", QUIET_HOURS: "Ruhezeit", NOBODY_HOME: "niemand zu Hause"},
    "en": {"ring": "Someone rang the doorbell", QUIET_HOURS: "quiet hours", NOBODY_HOME: "nobody home"},
}


def push_reason(quiet_active: bool, resident_states: list[str], last_push: datetime | None, now: datetime) -> str | None:
    """Why this ring is pushed (`quiet_hours`, `nobody_home`), or None.

    Nobody home = residents are configured and none of them is `home` (unknown counts as away: a missed ring is worse than one push too many).
    """
    if last_push is not None and now - last_push < MIN_GAP:
        return None
    if quiet_active:
        return QUIET_HOURS
    if resident_states and all(state != "home" for state in resident_states):
        return NOBODY_HOME
    return None


def push_message(reason: str, now: datetime, language: str) -> str:
    text = _TEXT["de" if language.lower().startswith("de") else "en"]
    return f"{text['ring']} ({now.strftime('%H:%M')}) · {text[reason]}"
