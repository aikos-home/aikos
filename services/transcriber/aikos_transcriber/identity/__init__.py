"""Who is speaking? Finds the self-introduction in an intercom transcript (rules first, local LLM as a guarded fallback).

Split from roomkey tools/talk_identity.py at d0d52b9, code unchanged. Public interface: identify(), by_rules(),
classify(), Identity, and the text helpers. The roomkey maintainers have the say over this package (review required).
"""
from __future__ import annotations

import re
import sys

from .classify import classify
from .llm import by_llm
from .model import Identity
from .patterns import L
from .roles import ROLES, SELF_DECLARED
from .rules import by_rules
from .text import WHISPER_PROMPT, clean, is_caption, is_noise, prompt_echo, strip_captions

__all__ = ["Identity", "ROLES", "SELF_DECLARED", "WHISPER_PROMPT", "by_llm", "by_rules", "classify", "clean", "identify",
           "is_caption", "is_noise", "prompt_echo", "strip_captions"]


def identify(text: str, known_names=(), llm_url: str = "", llm_model: str = "qwen3:8b", side: str = "door") -> Identity:
    text = clean(text)
    ident = by_rules(text, known_names, side)
    if ident.speaker and is_caption(ident.speaker):
        ident = Identity(message=text)                                # R24: a subtitle credit is nobody
    if ident.speaker or not llm_url or len(re.findall(L + r"{2,}", text)) < 3:
        return classify(ident, text, side)
    try:
        got = by_llm(text, llm_url, llm_model, side=side)
        if got and is_caption(got.speaker):
            got = None                                                # R24: the LLM took "ARD Text" for the speaker
        return classify(got or ident, text, side)
    except Exception as exc:  # LLM down or slow: the rules' answer stands
        print(f"identity: LLM skipped ({exc})", file=sys.stderr)
        return classify(ident, text, side)
