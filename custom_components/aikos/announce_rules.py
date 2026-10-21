"""The rules of the door announcements (sprachausgabe S10–S14, disclosure level §4b), no Home Assistant code.

After a ring (S11) the door says one sentence in a resident's own voice when a situation applies. The sentences are the
residents' own (S13); the code only picks which one, the model never decides what is said. The disclosure level (S3)
decides which situations may be told at all; every level includes the ones to its left:

| level | the door may say …                                                              |
|-------|---------------------------------------------------------------------------------|
| 0     | nothing (the default for every new house)                                        |
| 1     | that nobody can come or nobody is home; where to leave a parcel                  |
| 2, 3  | as 1 (garden, back-at: not yet)                                                  |
| 4     | where the residents are: only residents who agreed, only places released for it  |

Situations, the first that applies and has a sentence wins:
- parcel: a delivery is expected today (S14). Also when someone just comes close, not only after a ring.
- away: every resident is known to be away (an unknown state is not "away": telling a stranger the house is empty by mistake
  is worse than saying nothing).
- quiet: the bell is muted or it is quiet hours.
An empty sentence = that situation says nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

PARCEL, AWAY, QUIET = "parcel", "away", "quiet"
SITUATIONS = (PARCEL, AWAY, QUIET)
LEVEL_MAX = 4
LEVEL_TELL = 1          # from here the situations may be told
LEVEL_PLACES = 4        # from here where the residents are
TEXT_MAX = 200
PLACE_MAX = 40
PLACES_MAX = 20
WHERE = "{wo}"          # in the away sentence with places: replaced by "A ist beim Lidl und B ist im Fitnessstudio"
REPEAT_PAUSE = timedelta(seconds=60)   # a second ring within this time gets no second announcement


def clean(text: str, limit: int = TEXT_MAX) -> str:
    return " ".join((text or "").split())[:limit]


@dataclass
class Announcements:
    disclosure: int = 0
    voice: str = ""
    """Whose voice says the sentences (the person who saved them last, A45)."""
    texts: dict[str, str] = field(default_factory=dict)
    """situation → sentence; missing or "" = nothing said."""
    away_places: str = ""
    """The away sentence from level 4, with {wo}; "" = the away sentence also there."""
    places: dict[str, str] = field(default_factory=dict)
    """zone entity id → how the door says it ("beim Lidl"); zones not listed are never named."""
    named: list[str] = field(default_factory=list)
    """person entity ids whose place may be told (each person agrees for themselves)."""

    def check(self) -> None:
        if not 0 <= self.disclosure <= LEVEL_MAX:
            raise ValueError("disclosure 0 to 4")
        if self.away_places and WHERE not in self.away_places:
            raise ValueError("the away sentence with places needs {wo}")
        if any(WHERE in t for t in self.texts.values()):
            raise ValueError("{wo} only in the away sentence with places")
        if len(self.places) > PLACES_MAX:
            raise ValueError("too many places")

    def to_dict(self) -> dict[str, Any]:
        return {"disclosure": self.disclosure, "voice": self.voice, "texts": dict(self.texts),
                "away_places": self.away_places, "places": dict(self.places), "named": list(self.named)}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Announcements":
        if not isinstance(d, dict):
            return cls()
        try:
            texts, places, named = d.get("texts") or {}, d.get("places") or {}, d.get("named") or []
            if not isinstance(texts, dict) or not isinstance(places, dict) or not isinstance(named, list):
                raise TypeError("parts")
            a = cls(disclosure=int(d.get("disclosure") or 0), voice=str(d.get("voice") or ""),
                    texts={k: clean(str(v)) for k, v in texts.items() if k in SITUATIONS and v},
                    away_places=clean(str(d.get("away_places") or "")),
                    places={str(k): clean(str(v), PLACE_MAX) for k, v in places.items() if v},
                    named=[str(p) for p in named])
            a.check()
        except (TypeError, ValueError):
            return cls()
        return a


@dataclass(frozen=True)
class Resident:
    name: str
    state: str
    """The person's state: "home", "not_home", a zone's name, or unknown/unavailable."""
    place: str = ""
    """How the door says where they are; "" = not to be told (not agreed, or the zone isn't released)."""

    @property
    def known_away(self) -> bool:
        return self.state not in ("home", "unknown", "unavailable", "")


def where(residents: list[Resident]) -> str:
    """'A ist beim Lidl und B ist im Fitnessstudio' for the residents whose place may be told; "" = none."""
    parts = [f"{r.name} ist {r.place}" for r in residents if r.place and r.known_away]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " und " + parts[-1]


def sentence(a: Announcements, situation: str, residents: list[Resident]) -> str:
    """The sentence of a situation at this level ("" = nothing), whether or not it applies right now."""
    if a.disclosure < LEVEL_TELL:
        return ""
    if situation == AWAY and a.disclosure >= LEVEL_PLACES and a.away_places:
        wo = where(residents)
        if wo:
            return a.away_places.replace(WHERE, wo)
    return a.texts.get(situation, "")


def applying(*, parcel: bool, muted: bool, residents: list[Resident]) -> list[str]:
    """The situations that apply now, the most fitting first."""
    found = []
    if parcel:
        found.append(PARCEL)
    if residents and all(r.known_away for r in residents):
        found.append(AWAY)
    if muted:
        found.append(QUIET)
    return found


def pick(a: Announcements, *, parcel: bool, muted: bool, residents: list[Resident]) -> tuple[str, str] | None:
    """(situation, sentence) for a ring now: the first situation that applies and has a sentence; None = nothing said."""
    for s in applying(parcel=parcel, muted=muted, residents=residents):
        text = sentence(a, s, residents)
        if text:
            return s, text
    return None


def may_repeat(last: datetime | None, now: datetime) -> bool:
    return last is None or now - last >= REPEAT_PAUSE
