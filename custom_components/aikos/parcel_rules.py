"""Is a parcel coming today? Read from the carriers' notices (sprachausgabe S14/S15), no Home Assistant code, no model.

Only the sender's domain and the subject are used, never the mail's text. Fixed patterns:
- today: "In Zustellung" (Amazon), "… kommt heute", "Zustellung heute", "zwischen 13:45 und 15:45 Uhr …" (with that window)
- soon: "… wird gleich zugestellt"
- delivered: "Zugestellt" / "Geliefert" (Amazon), "… wurde zugestellt", "… ist da", "… liegt im Briefkasten / am Ablageort"
Anything else ("versendet", "ist unterwegs", "bald da", offers) is no notice.

Each shipment is followed by its key: Amazon's item ("„Akku-Set…“ und 2 weitere Artikel" → "akku-set"), other carriers by
the carrier (two parcels of one carrier on one day count as one: at worst a courier is not expected, never the other way
round). A parcel is expected while a key's latest notice today is "today" or "soon"; it is over with "delivered", at the end
of its time window plus a margin, or at LATEST_END.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

TODAY, SOON, DELIVERED = "today", "soon", "delivered"
CARRIERS = {
    "amazon.de": "Amazon", "dhl.de": "DHL", "dhl.com": "DHL", "deutschepost.de": "DHL", "dpd.de": "DPD",
    "hermesworld.com": "Hermes", "myhermes.de": "Hermes", "gls-pakete.de": "GLS", "gls-group.eu": "GLS",
    "gls-group.com": "GLS", "ups.com": "UPS",
}
"""Sender domain (or a subdomain of it) → carrier. Only these are read at all."""
LATEST_END = time(21, 0)          # no courier comes later; a notice without "delivered" is over then
WINDOW_MARGIN = timedelta(hours=1)

# "wurde/ist … zugestellt", but not "ist unterwegs und wird heute zugestellt"
_DELIVERED = re.compile(r"\b(wurde|ist)\b(?:(?!\b(wird|werden)\b).)*\b(zugestellt|geliefert|abgegeben|abgeholt)\b|"
                        r"^\s*zugestellt\b|\bist da\b|\bliegt\b|\bzur abholung\b|\babholbereit\b", re.I)
_SOON = re.compile(r"\bwird (gleich|jetzt|in kürze|bald) zugestellt\b|\bgleich bei ihnen\b|\bnächster stopp\b", re.I)
_TODAY = re.compile(r"\bkommt heute\b|zustellung heute\b|\bheute zugestellt\b|\bheute geliefert\b|\bin zustellung\b|"
                    r"\bzwischen \d{1,2}[:.]\d{2} und \d{1,2}[:.]\d{2}\b", re.I)
_WINDOW = re.compile(r"\bzwischen (\d{1,2})[:.](\d{2}) und (\d{1,2})[:.](\d{2})\b", re.I)
_AMAZON_TODAY = re.compile(r"^\s*in zustellung\b", re.I)
_AMAZON_DONE = re.compile(r"^\s*(zugestellt|geliefert)\b", re.I)
_QUOTES = "„“”\"'‚‘’«»"


@dataclass(frozen=True)
class Notice:
    carrier: str
    kind: str
    key: str
    at: datetime
    window: tuple[time, time] | None = None


@dataclass(frozen=True)
class Expectation:
    expected: bool = False
    carriers: tuple[str, ...] = ()
    soon: bool = False
    window: tuple[time, time] | None = None
    """The earliest window of the parcels still expected."""


def carrier_of(domain: str) -> str | None:
    d = (domain or "").lower().strip(".")
    for known, name in CARRIERS.items():
        if d == known or d.endswith("." + known):
            return name
    return None


def _item(subject: str) -> str:
    """Amazon's item: the text after the colon, without the quotes and "und N weitere Artikel"."""
    text = subject.split(":", 1)[1] if ":" in subject else subject
    text = re.sub(r"\s+und \d+ weitere[rn]? artikel\s*$", "", text, flags=re.I)
    return " ".join(text.strip().strip(_QUOTES).replace("“", "").replace("„", "").split()).casefold()


def classify(domain: str, subject: str, at: datetime) -> Notice | None:
    carrier = carrier_of(domain)
    subject = " ".join((subject or "").split())
    if carrier is None or not subject:
        return None
    if carrier == "Amazon":
        kind = TODAY if _AMAZON_TODAY.search(subject) else DELIVERED if _AMAZON_DONE.search(subject) else None
        return Notice(carrier, kind, "amazon:" + _item(subject), at) if kind else None
    if _DELIVERED.search(subject):
        kind = DELIVERED
    elif _SOON.search(subject):
        kind = SOON
    elif _TODAY.search(subject):
        kind = TODAY
    else:
        return None
    w = _WINDOW.search(subject)
    window = None
    if w:
        h1, m1, h2, m2 = (int(g) for g in w.groups())
        if h1 < 24 and h2 < 24 and m1 < 60 and m2 < 60:
            window = (time(h1, m1), time(h2, m2))
    # a DHL notice about an Amazon parcel is over with Amazon's own "delivered" as well
    key = "amazon-via:" + carrier.lower() if "amazon" in subject.lower() else carrier.lower()
    return Notice(carrier, kind, key, at, window)


def _over(n: Notice, now: datetime) -> bool:
    end = n.window[1] if n.window else LATEST_END
    limit = datetime.combine(now.date(), end, tzinfo=now.tzinfo) + (WINDOW_MARGIN if n.window else timedelta())
    return now >= limit


def expectation(notices: list[Notice], now: datetime) -> Expectation:
    """From today's notices (any order): is a parcel still expected now?"""
    today = sorted((n for n in notices if n.at.astimezone(now.tzinfo).date() == now.date()), key=lambda n: n.at)
    latest: dict[str, Notice] = {}
    for n in today:
        latest[n.key] = n
        if n.kind == DELIVERED and n.carrier == "Amazon":
            for k in [k for k in latest if k.startswith("amazon-via:")]:
                latest[k] = n   # Amazon says delivered: the carrier's notice about an Amazon parcel is over too
    pending = [n for n in latest.values() if n.kind in (TODAY, SOON) and not _over(n, now)]
    if not pending:
        return Expectation()
    windows = sorted(n.window for n in pending if n.window)
    return Expectation(True, tuple(sorted({n.carrier for n in pending})), any(n.kind == SOON for n in pending),
                       windows[0] if windows else None)
