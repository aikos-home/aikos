"""Numbers written out in German, before the model speaks and when the Whisper check compares: the model reads words
reliably, digits not, and Whisper writes a number one time as digits, the next time as a word. So both sides become words.

Covered: cardinals ("20" → "zwanzig", "1 Paket" → "ein Paket"), times ("10:13", "10.13 Uhr" → "zehn Uhr dreizehn"), dates
("22.10." → "zweiundzwanzigsten zehnten" after "am", else "-te"), ordinals after an article or "am/im/zum …", before a
lowercase word or before a month ("im 3. Stock", "am 3. Oktober"), decimals ("2,5" → "zwei Komma fünf"). Otherwise a number
with a full stop before a capitalised word ends the sentence ("um 3. Dann …"): it stays a cardinal. Very large numbers
stay digits.
"""

from __future__ import annotations

import re

ONES = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf",
        "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn"]
TENS = {2: "zwanzig", 3: "dreißig", 4: "vierzig", 5: "fünfzig", 6: "sechzig", 7: "siebzig", 8: "achtzig", 9: "neunzig"}
ORDINAL_STEM = {1: "erst", 2: "zweit", 3: "dritt", 7: "siebt", 8: "acht"}
MONTHS = {"januar", "jänner", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober",
          "november", "dezember"}
DATIVE = {"am", "im", "vom", "zum", "zur", "beim", "dem", "den", "des"}   # "am 3." → "dritten"
ARTICLE = DATIVE | {"der", "die", "das"}   # "im 3. Stock", "der 3. Versuch": an ordinal even before a noun
LIMIT = 1_000_000


def words(n: int, unit: bool = False) -> str:
    """The cardinal; `unit` = before a noun ("ein Paket"), else "eins"."""
    if n < 0 or n >= LIMIT:
        return str(n)
    if n < 20:
        return "ein" if n == 1 and unit else ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return TENS[t] if o == 0 else ("ein" if o == 1 else ONES[o]) + "und" + TENS[t]
    if n < 1000:
        h, r = divmod(n, 100)
        return ("ein" if h == 1 else ONES[h]) + "hundert" + (words(r) if r else "")
    th, r = divmod(n, 1000)
    return ("ein" if th == 1 else words(th)) + "tausend" + (words(r) if r else "")


def ordinal(n: int, ending: str) -> str:
    if n < 20:
        stem = ORDINAL_STEM.get(n) or ONES[n] + "t"
    else:
        stem = words(n) + "st"
    return stem + ending


def _ending(before: str) -> str:
    return "en" if before.lower() in DATIVE else "e"


_TIME = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)(\s*Uhr\b)?")
_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?")
_ORDINAL = re.compile(r"\b(\d{1,3})\.(?=\s+(\S+))")
_DECIMAL = re.compile(r"\b(\d+),(\d+)\b")
_CARDINAL = re.compile(r"\b(\d+)\b(?=(\s+\S+)?)")
_WORD_BEFORE = re.compile(r"(\S+)\s+$")


def _before(text: str, start: int) -> str:
    m = _WORD_BEFORE.search(text[:start])
    return m.group(1) if m else ""


def spell(text: str) -> str:
    def time_(m: re.Match) -> str:
        if m.group(3) is None and m.group(0)[2:3] == ".":   # "10.13" without "Uhr" is no time (a date or a decimal)
            return m.group(0)
        h, mi = int(m.group(1)), int(m.group(2))
        return f"{words(h)} Uhr" + (f" {words(mi)}" if mi else "")

    def date_(m: re.Match) -> str:
        d, mo = int(m.group(1)), int(m.group(2))
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            return m.group(0)
        e = _ending(_before(text_now, m.start()))
        out = f"{ordinal(d, e)} {ordinal(mo, e)}"
        return out + (f" {words(int(m.group(3)))}" if m.group(3) else "")

    def ordinal_(m: re.Match) -> str:
        nxt, before = m.group(2), _before(text_now, m.start())
        if not (nxt[:1].islower() or nxt.lower().strip(".,!?") in MONTHS or before.lower() in ARTICLE):
            return m.group(0)   # "um 3. Dann …": the number ends the sentence
        return ordinal(int(m.group(1)), _ending(before))

    def cardinal_(m: re.Match) -> str:
        nxt = (m.group(2) or "").strip()
        return words(int(m.group(1)), unit=nxt[:1].isupper())

    text_now = _TIME.sub(time_, text or "")
    text_now = _DATE.sub(date_, text_now)
    text_now = _ORDINAL.sub(ordinal_, text_now)
    text_now = _DECIMAL.sub(lambda m: f"{words(int(m.group(1)))} Komma {' '.join(ONES[int(c)] for c in m.group(2))}",
                            text_now)
    return _CARDINAL.sub(cardinal_, text_now)
