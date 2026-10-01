"""Echo of the resident in the door audio: when a resident talked, and dropping repeated sentences.

Part of the aikos transcriber (split from roomkey tools/talk_live.py, talk_identity.py and transcribe_publish.py at d0d52b9, code unchanged)."""
from __future__ import annotations

import datetime as dt
import os
import re
import time

from .ha import ha


def resident_talk(activity_file: str) -> tuple[float, float]:
    """(start, last audio) of the latest resident talk, from the room receiver's activity file; (0, 0) if unknown."""
    try:
        last = os.path.getmtime(activity_file)
        with open(activity_file) as f:
            start = float(f.read().strip() or last)
        return min(start, last), last
    except (OSError, ValueError):
        return 0.0, 0.0


def resident_overlap_s(activity_file: str, door_span: tuple[float, float]) -> float:
    """Seconds a resident talked during this door audio (door_span = start, end); 0 if unknown."""
    began, last = resident_talk(activity_file)
    if not began:
        return 0.0
    return max(0.0, min(last, door_span[1]) - max(began, door_span[0]))


def is_household(name: str, known_names) -> bool:
    """The speaker's name is one of the household's names ("Jonas", "Jonas Weber")."""
    known = {n.strip().lower() for n in known_names if n.strip()}
    return bool(known) and any(w.lower() in known for w in name.split())


def strip_echo(text: str, said: str) -> str:
    """Drop the sentences of a door transcript that mostly repeat what the resident said (the door mic hears the door
    speaker). Short sentences (< 3 words) stay: "Ja", "Danke" are too common to call an echo."""
    ref = {w.lower() for w in re.findall(r"\w+", said)}
    if not ref:
        return text
    keep = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        ws = [w.lower() for w in re.findall(r"\w+", sent)]
        if len(ws) >= 3 and sum(1 for w in ws if w in ref) / len(ws) >= 0.7:
            continue
        keep.append(sent)
    return " ".join(keep).strip()


def drop_echo(text: str, ha_url: str, token: str, door_span: tuple[float, float], activity_file: str,
              ref_entity: str = "sensor.talk_transcript", wait_s: float = 4.0) -> str:
    """The door mic hears the resident through the door speaker (voice v2: door mic on for the whole call). If a
    resident talked while this door audio was recorded (door_span = start, end), drop the door sentences that mostly
    repeat the resident's transcript, waiting up to wait_s for it. No overlap: nothing to drop (and no delay)."""
    began, _ = resident_talk(activity_file)
    if resident_overlap_s(activity_file, door_span) < 0.5:
        return text                                    # < 0.5 s together: not even a word of echo
    deadline = time.time() + wait_s
    while True:
        try:
            room = ha(ha_url, token, "GET", f"/api/states/{ref_entity}")
            made = dt.datetime.fromisoformat(room["state"]).timestamp()
        except Exception:
            return text
        if made >= began - 0.2 or time.time() >= deadline:
            return strip_echo(text, room["attributes"].get("text", ""))
        time.sleep(0.3)
