"""Whisper (local whisper.cpp server): transcription and the spoken language.

Part of the aikos transcriber (split from roomkey tools/transcribe_publish.py at d0d52b9, code unchanged)."""
from __future__ import annotations

import json
import re
import urllib.request
import uuid
from pathlib import Path

from .audio import padded

# Whisper's language codes → (German, English) display names. Others: Whisper's English name, capitalised.
LANGUAGES = {
    "de": ("Deutsch", "German"), "en": ("Englisch", "English"), "tr": ("Türkisch", "Turkish"), "ar": ("Arabisch", "Arabic"),
    "ru": ("Russisch", "Russian"), "uk": ("Ukrainisch", "Ukrainian"), "pl": ("Polnisch", "Polish"),
    "ro": ("Rumänisch", "Romanian"), "it": ("Italienisch", "Italian"), "fr": ("Französisch", "French"),
    "es": ("Spanisch", "Spanish"), "pt": ("Portugiesisch", "Portuguese"), "el": ("Griechisch", "Greek"),
    "hr": ("Kroatisch", "Croatian"), "sr": ("Serbisch", "Serbian"), "bs": ("Bosnisch", "Bosnian"), "bg": ("Bulgarisch", "Bulgarian"),
    "hu": ("Ungarisch", "Hungarian"), "cs": ("Tschechisch", "Czech"), "sk": ("Slowakisch", "Slovak"), "nl": ("Niederländisch", "Dutch"),
    "vi": ("Vietnamesisch", "Vietnamese"), "zh": ("Chinesisch", "Chinese"), "ja": ("Japanisch", "Japanese"),
    "ko": ("Koreanisch", "Korean"), "fa": ("Persisch", "Persian"), "ku": ("Kurdisch", "Kurdish"), "hi": ("Hindi", "Hindi"),
    "ur": ("Urdu", "Urdu"), "ta": ("Tamil", "Tamil"), "th": ("Thailändisch", "Thai"), "sq": ("Albanisch", "Albanian"),
    "da": ("Dänisch", "Danish"), "sv": ("Schwedisch", "Swedish"), "no": ("Norwegisch", "Norwegian"), "fi": ("Finnisch", "Finnish"),
    "he": ("Hebräisch", "Hebrew"), "lt": ("Litauisch", "Lithuanian"), "lv": ("Lettisch", "Latvian"), "et": ("Estnisch", "Estonian"),
    "sl": ("Slowenisch", "Slovenian"), "mk": ("Mazedonisch", "Macedonian"), "ka": ("Georgisch", "Georgian"),
    "hy": ("Armenisch", "Armenian"), "az": ("Aserbaidschanisch", "Azerbaijani"), "tl": ("Tagalog", "Tagalog"),
    "id": ("Indonesisch", "Indonesian"), "so": ("Somali", "Somali"), "sw": ("Suaheli", "Swahili"), "am": ("Amharisch", "Amharic"),
}
# Below this, Whisper's guess is not shown. English needs more: short German clips are sometimes taken for English.
LANG_MIN_P, LANG_MIN_P_EN = 0.6, 0.9


def whisper(url: str, wav: Path, language: str, prompt: str = "", verbose: bool = False):
    boundary = uuid.uuid4().hex
    parts = []
    fields = [("response_format", "verbose_json" if verbose else "json"), ("language", language), ("temperature", "0")] + \
        ([("prompt", prompt)] if prompt else [])
    for name, value in fields:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{wav.name}"\r\n'
                  f'Content-Type: audio/wav\r\n\r\n').encode() + padded(wav) + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    d["text"] = " ".join(d.get("text", "").split())
    return d if verbose else d["text"]


# words only one of the two languages uses — to see whether pass 1 really produced German
DE_ONLY = set("ich bin ist sind der die das den dem und nicht ein eine einen einem mit zu für sie wir hier auf komme kommt "
              "gleich bitte hallo danke ja nein mein meine heiße habe hab vom im es du euch uns mal noch schon auch was wer "
              "wo wie aber oder mich dich dir mir ihnen möchte will kann muss".split())
EN_ONLY = set("i i'm am is are the and not a an with to for you we here on coming please hello thanks yes no my have has "
              "from it it's this that can your our what who where how but or me want would could should".split())


def looks_german(text: str) -> bool:
    """Did Whisper's German pass produce German? For English it often just writes English."""
    if re.search(r"[^\W\d_]", text) and not re.search(r"[A-Za-zÄÖÜäöüß]", text):
        return False                                           # another script altogether
    ws = re.findall(r"[a-zäöüß']+", text.lower())
    de, en = sum(w in DE_ONLY for w in ws), sum(w in EN_ONLY for w in ws)
    return len(ws) <= 2 or de >= en


def spoken_language(d: dict) -> tuple[str, float]:
    """(code, probability) of Whisper's language detection; "de" when unsure."""
    probs = d.get("language_probabilities") or {}
    code, p = max(probs.items(), key=lambda kv: kv[1]) if probs else ("de", 1.0)
    return (code, p) if p >= (LANG_MIN_P_EN if code == "en" else LANG_MIN_P) else ("de", p)
