"""W3 mic health rules: when do the transcriber's verdicts mean "this mic is broken"? No Home Assistant imports.

One bad recording can be chance (someone covered the mic); two bad ones in a row from the same device are a warning.
The first good recording clears it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BAD_IN_A_ROW = 2
OK = "ok"
PROBLEM, CLEARED = "problem", "cleared"

_TEXT = {
    "de": {"silent": "Mikro an {d} sendet nur Stille – Kabel prüfen", "clipping": "Mikro an {d} übersteuert – Kabel prüfen",
           "title": "aikos: Mikro"},
    "en": {"silent": "Mic at {d} sends only silence – check its wiring", "clipping": "Mic at {d} is clipping – check its wiring",
           "title": "aikos: mic"},
}


@dataclass
class DeviceMic:
    verdict: str = OK
    bad_in_a_row: int = 0
    problem: bool = False
    since: str = ""
    last: dict[str, Any] = field(default_factory=dict)


@dataclass
class MicHealth:
    devices: dict[str, DeviceMic] = field(default_factory=dict)

    def note(self, device: str, verdict: str, when: str, numbers: dict[str, Any]) -> str | None:
        """Take one verdict. Returns PROBLEM when this device just turned bad, CLEARED when it just recovered, else None."""
        d = self.devices.setdefault(device, DeviceMic())
        d.verdict, d.last = verdict, dict(numbers)
        if verdict == OK:
            d.bad_in_a_row = 0
            if d.problem:
                d.problem, d.since = False, ""
                return CLEARED
            return None
        d.bad_in_a_row += 1
        if not d.problem and d.bad_in_a_row >= BAD_IN_A_ROW:
            d.problem, d.since = True, when
            return PROBLEM
        return None

    @property
    def problem_devices(self) -> list[str]:
        return sorted(name for name, d in self.devices.items() if d.problem)


def message(device: str, verdict: str, language: str) -> tuple[str, str]:
    text = _TEXT["de" if language.lower().startswith("de") else "en"]
    return text["title"], text.get(verdict, text["silent"]).format(d=device)
