"""Speech to text for Home Assistant (aikos voice, the owner's rule SB-R4 of 16.11.): a sentence a device recorded (a remote's
voice key, later a RoomKey) is written down by Whisper. It goes to the shared Whisper through the aikos hub, never to the live
Whisper of the door's transcription, so a voice command and a door call never queue behind each other (measured 16.11.:
both at once cost each sentence ~0.4 s, nothing waits).

Whisper "hears" subtitle credits in silence or noise ("Vielen Dank fürs Zuschauen." from a remote's empty recording,
16.11.). Such a result counts as nothing heard; a command is never made from it.
"""

from __future__ import annotations

import json
import re
import urllib.request

from .verify import wav_bytes

MAX_S = 30                  # longer recordings are cut: a command is a sentence, a stuck key must not tie up Whisper
# The transcriber's list (services/transcriber, identity/text.py, R24), kept in step by hand: the two blocks are deployed apart
# and don't import each other.
BROADCASTERS = r"(?:ard|zdf|funk|ndr|wdr|swr|mdr|br|hr|rbb|sr|orf|srf|3sat|arte|kika|phoenix)"
HALLUCINATIONS = [r"untertitel", r"amara\.org", r"(?:dank|danke)\w* (?:fürs|für's|für das) zu(?:schauen|sehen|hören)",
                  r"copyright", rf"\b{BROADCASTERS} \d{{4}}\b", r"thanks for watching", r"subtitles? by", r"in die kommentare",
                  r"abonnier", r"bis zum nächsten (?:mal|video)", r"(?:like|daumen) (?:da|hoch)", r"^tschüss\.?$",
                  r"^(?:musik|applaus|lachen|stille|gelächter|klingeln|piepen|rauschen|music|applause|silence)[.!]?$",
                  r"\b(?:ard|zdf)[ -]?text\b", r"\bvideotext\b", rf"\bim auftrag (?:des|der|von) {BROADCASTERS}\b",
                  rf"\b(?:ard|zdf) für {BROADCASTERS}\b", r"^(?:\w+\s+){0,2}im auftrag(?:\s+(?:des|der|von))?[.!,]?$"]
SPOKEN = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")


def clean(text: str) -> str:
    """The sentence without Whisper's sound captions ("[Musik]", "*Klingeln*") and subtitle hallucinations, sentence by
    sentence; "" when nothing spoken is left."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*|♪[^♪]*♪", " ", text or "")
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    kept = " ".join(p for p in parts if not any(re.search(h, p, re.I) for h in HALLUCINATIONS)).strip()
    return kept if SPOKEN.search(kept) else ""


class Recognizer:
    """Writes a recording down with a whisper-server (`/v1/audio/transcriptions`); `url` is the hub path of this service's
    client (e.g. http://127.0.0.1/c/aikos-tts), the same Whisper the sentence check uses."""

    def __init__(self, url: str, language: str = "de", timeout: float = 30.0) -> None:
        self.url, self.language, self.timeout = url.rstrip("/"), language, timeout

    def transcribe(self, pcm: bytes, rate: int) -> str:
        """16-bit mono PCM at `rate` → the cleaned sentence ("" = nothing heard). Raises on a network or Whisper error."""
        pcm = pcm[:MAX_S * rate * 2]
        b = "----aikos-stt"
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"said.wav\"\r\n"
                f"Content-Type: audio/wav\r\n\r\n").encode() + wav_bytes(pcm, rate) + "".join(
            f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}"
            for k, v in (("language", self.language), ("response_format", "json"), ("temperature", "0"))).encode() \
            + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(self.url + "/v1/audio/transcriptions", method="POST", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return clean(str(json.loads(r.read()).get("text", "")))
