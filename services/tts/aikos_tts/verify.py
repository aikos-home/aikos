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

WORD = re.compile(r"[0-9a-zäöüß]+")
MIN_COVERAGE = 0.85          # share of the text's words that must be heard, in order
MAX_LEADING = 0              # words heard before the first word of the text (live: "Gah, bitte ...")
TAIL_S = 0.25                # kept after the last word (its end is a little early)


def norm_words(text: str) -> list[str]:
    return WORD.findall((text or "").lower().replace("ß", "ss"))


@dataclass(frozen=True)
class Heard:
    word: str
    start: float
    end: float


def join_tokens(segments: list[list[tuple[str, float, float]]]) -> list[Heard]:
    """Whisper's "words" are tokens ("pak", "et"): a token without a leading space continues the word before it;
    punctuation and a new segment end a word."""
    out: list[Heard] = []
    for seg in segments:
        open_word = False
        for raw, start, end in seg:
            parts = norm_words(raw)
            if not parts:
                open_word = False
                continue
            for i, part in enumerate(parts):
                if i == 0 and open_word and not raw[:1].isspace():
                    prev = out[-1]
                    out[-1] = Heard(prev.word + part, prev.start, end)
                else:
                    out.append(Heard(part, start, end))
            open_word = True
    return out


@dataclass(frozen=True)
class Verdict:
    ok: bool
    cut_s: float | None
    coverage: float
    heard: str


def judge(expected: str, heard: list[Heard], duration_s: float) -> Verdict:
    """Pure rule: may this take be used, and where does the text end in it?"""
    want = [w.replace("ß", "ss") for w in norm_words(expected)]
    got = [w.word for w in heard]
    text = " ".join(got)
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
