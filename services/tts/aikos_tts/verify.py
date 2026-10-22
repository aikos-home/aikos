"""The model never decides what is said (the owner's rule, 21.10.): every generated sentence is written back by the local Whisper and
compared with the text. Whatever the model adds after the last word of the text is cut off; if words are missing or the
start is wrong, the sentence is made again; if it still does not fit, nothing is spoken (the door shows the text only).
"""

from __future__ import annotations

import difflib
import io
import json
import re
import urllib.request
import wave
from dataclasses import dataclass

from .numbers import spell

WORD = re.compile(r"[0-9a-zäöüß]+")
MIN_COVERAGE = 0.85          # share of the text's words that must be heard, in order
MAX_LEADING = 0              # words heard before the first word of the text (live: "Gah, bitte ...")
TAIL_S = 0.25                # kept after the last word (its end is a little early)
ONE = {"ein", "eins", "eine", "einen", "einem", "einer", "eines"}   # "1" is read one way, heard another


def norm_words(text: str) -> list[str]:
    """Words for comparing: lower case, numbers written out (Whisper writes "10" one time, "zehn" the next)."""
    return WORD.findall(spell(text or "").lower().replace("ß", "ss"))


@dataclass(frozen=True)
class Heard:
    word: str
    start: float
    end: float


def join_tokens(segments: list[list[tuple[str, float, float]]]) -> list[Heard]:
    """Whisper's "words" are tokens ("pak", "et", "10", ".", "13"): a token without a leading space continues the word
    before it, a new segment starts one. The heard text is then written out as a whole (numbers.py), so "10.13 Uhr" or
    "22.10." become the same words as in the text; each word keeps the times of the token word it came from."""
    raw: list[tuple[str, float, float]] = []
    for seg in segments:
        first = True
        for tok, start, end in seg:
            if not tok.strip():
                continue
            if raw and not first and not tok[:1].isspace():
                word, s0, _ = raw[-1]
                raw[-1] = (word + tok, s0, end)
            else:
                raw.append((tok.strip(), start, end))
            first = False
    words = norm_words(" ".join(w for w, _, _ in raw))
    each = [norm_words(w) for w, _, _ in raw]
    out: list[Heard] = []
    if sum(len(e) for e in each) == len(words):     # nothing written out differently in context: word by word
        for (_, start, end), parts in zip(raw, each):
            out += [Heard(w, start, end) for w in parts]
        return [Heard(w, h.start, h.end) for w, h in zip(words, out)]
    for j, w in enumerate(words):                    # else (a time, a date): the times spread over the token words
        i = min(len(raw) - 1, j * len(raw) // max(1, len(words)))
        out.append(Heard(w, raw[i][1], raw[i][2]))
    return out


@dataclass(frozen=True)
class Verdict:
    ok: bool
    cut_s: float | None
    coverage: float
    heard: str


def edits(a: str, b: str) -> int:
    """Levenshtein distance (letters inserted, removed or changed)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def same_word(want: str, got: str) -> bool:
    """The text's word, as Whisper may write it:
    - the same, or an inflected form of it ("schelm" / "schelmen"): one starts with the other, at least 4 letters, at most
      2 more;
    - a name or a made-up word spelled a little differently (the owner's tests, 22.10.: "slebi" / "slevi", "zanni" /
      "sanni"): from 5 letters one letter off, from 8 letters two.
    Short words must be the same: "Haus" is never "Maus"."""
    if want == got or {want, got} <= ONE:
        return True
    short, long_ = sorted((want, got), key=len)
    if len(short) >= 4 and len(long_) - len(short) <= 2 and long_.startswith(short):
        return True
    allowed = 2 if len(short) >= 8 else 1 if len(short) >= 5 else 0
    return allowed > 0 and abs(len(want) - len(got)) <= allowed and edits(want, got) <= allowed


def compounds(want: list[str], heard: list[Heard]) -> list[Heard]:
    """Whisper joins or splits words the text has the other way ("weg gehen" / "weggehen", "Haus tür" / "Haustür"):
    a heard word that is two of the text's words in a row counts as both, two heard words that make one of the text's
    words count as that one."""
    pairs = {want[j] + want[j + 1]: (want[j], want[j + 1]) for j in range(len(want) - 1)}
    words = set(want)
    out: list[Heard] = []
    i = 0
    while i < len(heard):
        w = heard[i]
        if w.word in pairs and w.word not in words:
            a, b = pairs[w.word]
            out += [Heard(a, w.start, w.end), Heard(b, w.start, w.end)]
            i += 1
            continue
        if i + 1 < len(heard) and w.word not in words and w.word + heard[i + 1].word in words:
            out.append(Heard(w.word + heard[i + 1].word, w.start, heard[i + 1].end))
            i += 2
            continue
        out.append(w)
        i += 1
    return out


def judge(expected: str, heard: list[Heard], duration_s: float) -> Verdict:
    """Pure rule: may this take be used, and where does the text end in it?"""
    want = [w.replace("ß", "ss") for w in norm_words(expected)]
    text = " ".join(w.word for w in heard)
    heard = compounds(want, heard)
    got = [next((x for x in want if same_word(x, w.word)), w.word) for w in heard]
    if not want:
        return Verdict(False, None, 0.0, text)
    blocks = [b for b in difflib.SequenceMatcher(None, want, got, autojunk=False).get_matching_blocks() if b.size]
    matched = sum(b.size for b in blocks)
    coverage = matched / len(want)
    if not blocks or coverage < MIN_COVERAGE or blocks[0].b > MAX_LEADING:
        return Verdict(False, None, coverage, text)
    last = blocks[-1].b + blocks[-1].size - 1          # index in `heard` of the text's last matched word
    if last == len(heard) - 1:
        return Verdict(True, None, coverage, text)      # nothing after it: keep the whole take
    cut = min(heard[last].end + TAIL_S, heard[last + 1].start, duration_s)
    return Verdict(True, cut, coverage, text)


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


class WhisperChecker:
    """Writes a take back with the local whisper-server (`/v1/audio/transcriptions`, verbose JSON with word times)."""

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        self.url, self.timeout = url.rstrip("/"), timeout

    def hear(self, pcm: bytes, rate: int) -> list[Heard]:
        b = "----aikos-tts"
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"take.wav\"\r\n"
                f"Content-Type: audio/wav\r\n\r\n").encode() + wav_bytes(pcm, rate) + "".join(
            f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}"
            for k, v in (("language", "de"), ("response_format", "verbose_json"), ("temperature", "0"))).encode() + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(self.url + "/v1/audio/transcriptions", method="POST", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read())
        return join_tokens([[(str(w.get("word", "")), float(w.get("start", 0)), float(w.get("end", 0)))
                             for w in seg.get("words") or []] for seg in data.get("segments") or []])

    def check(self, expected: str, pcm: bytes, rate: int) -> Verdict:
        return judge(expected, self.hear(pcm, rate), len(pcm) / 2 / rate)
