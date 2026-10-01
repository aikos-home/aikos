"""Equivalence check: the split identity package must behave exactly like roomkey tools/talk_identity.py.

    ROOMKEY_TOOLS=<path to roomkey/tools at the reference commit> python tests/equivalence/compare_identity.py [cases.json ...]

Compares, for every input text (rule cases, type cases, the given eval case files, noise/echo lists) and both sides:
by_rules (with and without known names), classify, identify without LLM, the text helpers, strip_echo, and the LLM path
with canned answers (network replaced). Exit code 1 on the first difference. Not part of CI (needs the old code).
"""
import importlib.util
import io
import json
import os
import sys
import urllib.request
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))           # services/transcriber
sys.path.insert(0, str(HERE.parents[1]))           # tests (identity_cases)
from aikos_transcriber import identity as new      # noqa: E402
from aikos_transcriber import echo as new_echo     # noqa: E402
from identity_cases import CASES, TYPE_CASES       # noqa: E402

spec = importlib.util.spec_from_file_location("old_talk_identity", Path(os.environ["ROOMKEY_TOOLS"]) / "talk_identity.py")
old = importlib.util.module_from_spec(spec)
sys.modules["old_talk_identity"] = old             # dataclasses look the module up while the class is created
spec.loader.exec_module(old)

texts = [t.removeprefix("room:") for t, _, _ in CASES] + [t for t, _, _, _ in TYPE_CASES]
for f in sys.argv[1:]:
    texts += [c.get("text") or c.get("reference") or "" for c in json.load(io.open(f, encoding="utf-8"))]   # cases | real manifest
texts += ["♪♪", "¶¶", "Untertitel im Auftrag des ZDF, 2020", " ", "Vielen Dank fürs Zuschauen!", "BELLS CHIMING", "Musik",
          "[Musik]", "(Glocken läuten)", "*Klingeln*", "Polizei, Feuerwehr, Rettungsdienst, Schornsteinfeger.",
          "Hermes, DPD, UPS, GLS, FedEx", "Haustür-Sprechanlage.", "Telekom, Vodafone.", "Hallo? [Musik] Ist da jemand?",
          "DHL, Paket!", "Polizei! Vielen Dank fürs Zuschauen!", "您好,我是沙利沃。", "Paul, Marie.", "Hier ist Paul."]
texts = list(dict.fromkeys(texts))
checks = 0


def same(label, a, b):
    global checks
    checks += 1
    if a != b:
        print(f"DIFFERENT {label}\n  old: {a!r}\n  new: {b!r}")
        sys.exit(1)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def canned(answer):
    """urlopen replacement: an Ollama /api/chat reply whose content is `answer` (JSON)."""
    def urlopen(req, timeout=None):
        return FakeResponse(json.dumps({"message": {"content": json.dumps(answer, ensure_ascii=False)}}).encode())
    return urlopen


real_urlopen = urllib.request.urlopen
for t in texts:
    for side in ("door", "room"):
        for names in ((), ("Jonas", "Anna"), ("Paul", "Marie")):
            same(f"by_rules {side} {names} {t!r}", asdict(old.by_rules(t, names, side)), asdict(new.by_rules(t, names, side)))
        same(f"classify {side} {t!r}", asdict(old.classify(old.by_rules(t, side=side), old.clean(t), side)),
             asdict(new.classify(new.by_rules(t, side=side), new.clean(t), side)))
        same(f"identify {side} {t!r}", asdict(old.identify(t, side=side)), asdict(new.identify(t, side=side)))
        # LLM path with canned answers: the guards must decide the same way
        words = [w for w in t.replace(",", " ").replace(".", " ").split() if w[:1].isupper()]
        for ans in ([{"speaker": w, "kind": k, "role": r} for w in words[:3] for k in ("name", "role") for r in ("", "neighbour")]
                    + [{"speaker": "", "kind": "none", "role": ""}]):
            urllib.request.urlopen = canned(ans)
            try:
                o = old.by_llm(t, "http://llm.invalid", "m", side=side)
                n = new.by_llm(t, "http://llm.invalid", "m", side=side)
            finally:
                urllib.request.urlopen = real_urlopen
            same(f"by_llm {side} {ans} {t!r}", o and asdict(o), n and asdict(n))
    same(f"clean {t!r}", old.clean(t), new.clean(t))
    same(f"is_noise {t!r}", old.is_noise(t), new.is_noise(t))
    same(f"prompt_echo {t!r}", old.prompt_echo(t), new.prompt_echo(t))
    same(f"strip_captions {t!r}", old.strip_captions(t), new.strip_captions(t))
    for said in ("Hier ist Marie, ich komme gleich runter.", t):
        same(f"strip_echo {t!r} / {said!r}", old.strip_echo(t, said), new_echo.strip_echo(t, said))
same("WHISPER_PROMPT", old.WHISPER_PROMPT, new.WHISPER_PROMPT)
same("ROLES", old.ROLES, new.ROLES)
print(f"identical: {checks} checks over {len(texts)} texts")
