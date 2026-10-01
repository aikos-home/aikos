"""Cleaning a transcript: captions, hallucinations, prompt echoes, fillers.

Part of the aikos transcriber (split from roomkey tools/talk_identity.py at d0d52b9, code unchanged).
"Who is speaking" logic: the roomkey maintainers have the say here (review required)."""
from __future__ import annotations

import re

from .patterns import FILLERS, L, UP, WORD

# Whisper "hears" these in silence or noise (training-data subtitles). They are removed, never shown.
HALLUCINATIONS = [r"untertitel", r"amara\.org", r"(?:dank|danke)\w* (?:fürs|für's|für das) zu(?:schauen|sehen|hören)",
                  r"copyright", r"swr \d{4}", r"wdr \d{4}", r"thanks for watching", r"subtitles? by", r"in die kommentare",
                  r"abonnier", r"bis zum nächsten (?:mal|video)", r"(?:like|daumen) (?:da|hoch)", r"^tschüss\.?$",
                  r"^(?:musik|applaus|lachen|stille|gelächter|klingeln|piepen|rauschen|music|applause|silence)[.!]?$"]
# Vocabulary hint for Whisper (initial prompt): the words people say at a German front door.
# A word list, not sentences: then a real "Hier ist die Polizei" never looks like an echo of the hint.
WHISPER_PROMPT = ("Haustür-Sprechanlage. Paketdienst, DHL, Hermes, DPD, UPS, GLS, FedEx, Amazon, Deutsche Post, "
                  "Lieferando, Wolt, Uber Eats, Flink, Rewe, Polizei, Feuerwehr, Rettungsdienst, Schornsteinfeger, "
                  "Stadtwerke, Telekom, Vodafone, Hausmeister, Hausverwaltung, Pflegedienst, Nachbarin.")
PROMPT_WORDS = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", WHISPER_PROMPT)} - {"deutsche", "post"}


def prompt_echo(text: str, prompt: str = WHISPER_PROMPT) -> bool:
    """Whisper sometimes answers unclear audio with (a piece of) its own prompt ("Hier ist die Polizei, die Feuerwehr,
    die Nachbarin."): 4+ words in the same order as in the prompt, or 4+ of the prompt's brand/role words."""
    ws = [w.lower() for w in re.findall(rf"{WORD}", text)]
    ps = [w.lower() for w in re.findall(rf"{WORD}", prompt)]
    if len(set(ws) & PROMPT_WORDS) >= 4 or "sprechanlage" in text.lower():
        return True
    if len(ws) >= 2 and " ".join(ws) in " ".join(ps):  # the whole "transcript" is a piece of the hint ("Anna, Jonas.")
        return True
    grams = {tuple(ps[i:i + 4]) for i in range(len(ps) - 3)}
    return any(tuple(ws[i:i + 4]) in grams for i in range(len(ws) - 3))


# ── cleaning ──────────────────────────────────────────────────────────────────
def strip_captions(text: str) -> str:
    """Remove Whisper's sound captions ("[Musik]", "(Glocken läuten)", "*Klingeln*", "BELLS CHIMING") and its
    subtitle hallucinations ("Untertitel im Auftrag des ZDF"), sentence by sentence — the rest is kept."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*|♪[^♪]*♪", " ", text)
    cased = [c for c in text if c.isupper() or c.islower()]
    if cased and not any(c.islower() for c in cased):   # all capitals = a caption ("BELLS CHIMING"); 汉字 has no case
        return ""
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(p for p in parts if not any(re.search(h, p, re.I) for h in HALLUCINATIONS)).strip()


def is_noise(text: str) -> bool:
    """True if the transcript has no spoken words: only captions, symbols or Whisper hallucinations."""
    return not re.search(L + r"{2,}", strip_captions(text))


def clean(text: str) -> str:
    """Captions, hallucinations and fillers out ("hier ist, äh, der Jonas" → "hier ist, der Jonas")."""
    text = strip_captions(text)
    text = re.sub(FILLERS, "", text, flags=re.I)
    text = re.sub(r"(?<!\w)d['’](?=[" + UP + "])", "", text)          # Swiss/Alemannic "d'Frau Huber"
    text = re.sub(r"\b(und|oder)\s*,\s*", r"\1 ", text, flags=re.I)  # "Yusuf und, äh, Can" → "Yusuf und Can"
    return re.sub(r"\s+([,.!?])", r"\1", " ".join(text.split()))
