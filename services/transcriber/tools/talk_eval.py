#!/usr/bin/env python3
"""
talk_eval.py — end-to-end test of "who is speaking": voice → Whisper → aikos_transcriber.identity. Dev tool, not in CI
(needs numpy, macOS `say`, the local Whisper server and Ollama); CI runs tests/test_identity_snapshot.py instead.

Every test case is spoken (macOS `say`: German voices, and foreign voices reading German = accented
German) or taken from a real recording, degraded like a real doorstep/room (street noise, voices in
the background, distance and echo, too loud, telephone-like), transcribed by the local Whisper server
and run through aikos_transcriber.identity. Scores:
  • recognition rate — the detected speaker matches the case (or is empty when nobody introduced themselves)
  • completeness     — share of the spoken words that arrive in the transcript
  • text-only rate   — the detector on the case's ideal transcript (separates Whisper errors from detector errors)

    python3 services/transcriber/tools/talk_eval.py --cases services/transcriber/tests/eval/cases_*.json --text-only
    python3 services/transcriber/tools/talk_eval.py --cases … [--real manifest.json] --out /tmp/talk_eval \
        [--no-llm | --llm-model qwen3:8b] [--prompt "…"] [--only accent,noisy]
    (state 2026-10-01: text only 98.9 % over the 716 cases with qwen3:8b; rules alone 92.9 %)

Case format (JSON list): {"id", "category", "side": "door"|"room", "say": spoken text, "text": ideal transcript,
  "expect_speaker_any": [["Anna"], ...] (alternatives of tokens that must all appear; [] = speaker must be empty;
  the alternative ["∅"] = empty is also fine, for cases a careful human would call ambiguous),
  "expect_message_contains": "", "voice": optional say-voice, "condition": optional condition}
Real-recording manifest: {"file", "reference", "expect_speaker_any", "accent", ...}, files next to the manifest.
Needs numpy and macOS `say`. Audio and transcripts are cached in --out, so re-runs only redo what changed.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import urllib.request
import uuid
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # services/transcriber
from aikos_transcriber.identity import WHISPER_PROMPT, identify, is_noise, prompt_echo, strip_captions  # noqa: E402

RATE = 16000
NATIVE = ["Anna", "Eddy (German (Germany))", "Flo (German (Germany))", "Grandma (German (Germany))",
          "Grandpa (German (Germany))", "Reed (German (Germany))", "Rocko (German (Germany))",
          "Sandy (German (Germany))", "Shelley (German (Germany))"]
# foreign voices reading German: the largest immigrant languages in Germany first
ACCENT = ["Yelda", "Milena", "Lesya", "Zosia", "Ioana", "Majed", "Linh", "Alice", "Melina", "Lana",
          "Daria", "Samantha", "Mónica", "Tünde", "Jacques"]
CONDITIONS = ["clean", "street", "babble", "far", "loud", "phone"]


# ── audio ─────────────────────────────────────────────────────────────────────
def read_wav(p: Path) -> np.ndarray:
    with wave.open(str(p)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == RATE, p
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768


def wav_bytes(x: np.ndarray) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return b.getvalue()


def synth(text: str, voice: str, cache: Path) -> np.ndarray:
    key = hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()[:16]
    p = cache / f"tts_{key}.wav"
    if not p.exists():
        subprocess.run(["say", "-v", voice, "-o", str(p), "--file-format=WAVE", "--data-format=LEI16@16000", text],
                       check=True, capture_output=True)
    return read_wav(p)


def rms(x):
    return float(np.sqrt(np.mean(x ** 2)) + 1e-9)


def colored_noise(n, rng, beta):  # beta 0 white, 1 pink, 2 brown
    f = np.fft.rfftfreq(n, 1 / RATE)
    spec = (rng.standard_normal(len(f)) + 1j * rng.standard_normal(len(f))) / np.maximum(f, 20) ** (beta / 2)
    x = np.fft.irfft(spec, n)
    return x / rms(x)


def reverb(x, rng, rt60=0.45, wet=0.35):
    n = int(rt60 * RATE)
    ir = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
    y = np.fft.irfft(np.fft.rfft(x, len(x) + n) * np.fft.rfft(ir / rms(ir) / 40, len(x) + n))[: len(x)]
    return (1 - wet) * x + wet * y


def bandpass_phone(x):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    X[(f < 300) | (f > 3400)] *= 0.05
    return np.fft.irfft(X, len(x))


def limiter(x, ceiling=0.8):  # the key's firmware limiter (roomkey_dsp.h), vectorised roughly
    env = np.maximum.accumulate(np.abs(x))  # conservative: never releases within one utterance
    return np.where(env > ceiling, x * ceiling / np.maximum(env, 1e-9), x)


def highpass120(x):  # the key's firmware high-pass (roomkey_mic.yaml), as a brick-wall approximation
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    X[f < 120] *= np.clip(f[f < 120] / 120, 0, 1) ** 2
    return np.fft.irfft(X, len(x))


def degrade(x: np.ndarray, cond: str, rng, babble_src: list[np.ndarray]) -> np.ndarray:
    lead, tail = rng.uniform(0.2, 0.8), rng.uniform(0.4, 1.0)   # the key starts before and stops after speech
    x = np.concatenate([np.zeros(int(lead * RATE)), x, np.zeros(int(tail * RATE))]).astype(np.float64)
    x = x / rms(x) * 10 ** (-24 / 20)                             # speech at −24 dBFS RMS
    floor = colored_noise(len(x), rng, 1) * 10 ** (-62 / 20)      # every room hisses a little
    if cond == "street":
        x = x + colored_noise(len(x), rng, 2) * rms(x) * 10 ** (-6 / 20) + colored_noise(len(x), rng, 1) * rms(x) * 10 ** (-18 / 20)
    elif cond == "babble":
        b = np.zeros(len(x))
        for src in babble_src[:3]:
            s = np.resize(src, len(x)) if len(src) else np.zeros(len(x))
            b += np.roll(s, int(rng.integers(0, len(x))))
        x = x + b / rms(b) * rms(x) * 10 ** (-15 / 20)      # people talking a few metres away
    elif cond == "far":
        x = reverb(x, rng) * 10 ** (-14 / 20)
    elif cond == "loud":
        x = limiter(x * 10 ** (20 / 20))                           # shouted into the mic, firmware limiter
    elif cond == "phone":
        x = bandpass_phone(x)
    return highpass120(x + floor).astype(np.float32)


# ── whisper ───────────────────────────────────────────────────────────────────
def whisper(url: str, audio: bytes, language: str, prompt: str) -> str:
    boundary = uuid.uuid4().hex
    fields = [("response_format", "json"), ("language", language), ("temperature", "0")]
    if prompt:
        fields.append(("prompt", prompt))
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields)
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
             f"Content-Type: audio/wav\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return " ".join(json.loads(r.read())["text"].split())


# ── scoring ───────────────────────────────────────────────────────────────────
def words(s: str) -> list[str]:
    s = s.lower().replace("ß", "ss")
    return re.findall(r"[a-zäöüàâçéèêëîïôûùüÿñæœıšžčćğşăîțș0-9]+", s)


def recall(ref: str, hyp: str) -> float:
    r, h = collections.Counter(words(ref)), collections.Counter(words(hyp))
    return sum((r & h).values()) / max(1, sum(r.values()))


def speaker_ok(expect: list[list[str]], got: str) -> bool:
    if not expect:
        return got == ""
    g = got.lower()
    return any((got == "") if alt == ["∅"] else (bool(g) and all(t.lower() in g for t in alt)) for alt in expect)


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", nargs="*", default=[], type=Path)
    ap.add_argument("--real", nargs="*", default=[], type=Path, help="manifest(s) of real recordings")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--whisper-url", default="http://127.0.0.1:6667/v1/audio/transcriptions")
    ap.add_argument("--language", default="de")
    ap.add_argument("--prompt", default="", help='Whisper initial prompt; "default" = identity WHISPER_PROMPT')
    ap.add_argument("--llm-url", default="http://127.0.0.1:11434")
    ap.add_argument("--llm-model", default="qwen3:8b")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--text-only", action="store_true", help="skip audio: detector on the ideal transcripts")
    ap.add_argument("--only", default="", help="comma list of categories/voice groups/conditions to keep")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    if a.prompt == "default":
        a.prompt = WHISPER_PROMPT
    a.out.mkdir(parents=True, exist_ok=True)
    cache = a.out / "cache"
    cache.mkdir(exist_ok=True)
    tcache_p = a.out / "transcripts.json"
    tcache = json.loads(tcache_p.read_text(encoding="utf-8")) if tcache_p.exists() else {}
    llm = "" if a.no_llm else a.llm_url

    items = []
    for f in a.cases:
        for i, c in enumerate(json.loads(f.read_text(encoding="utf-8"))):
            c = dict(c)
            h = int(hashlib.sha1(c["id"].encode()).hexdigest(), 16)
            accented = c.get("category", "") in ("foreigner", "foreigners", "foreign", "accent", "broken") or "accent" in c.get("notes", "").lower()
            if not c.get("voice"):
                pool = ACCENT if (accented or h % 3 == 0) else NATIVE
                c["voice"] = pool[h % len(pool)]
            c.setdefault("condition", CONDITIONS[(h // 7) % len(CONDITIONS)])
            c["group"] = "accent" if c["voice"] in ACCENT else "native"
            c["source"] = "tts"
            items.append(c)
    for m in a.real:
        for r in json.loads(m.read_text(encoding="utf-8")):
            items.append({"id": "real-" + Path(r["file"]).stem, "category": "real-" + ("intro" if r.get("intro_like") else "other"),
                          "side": "door", "say": r["reference"], "text": r["reference"], "file": str(m.parent / r["file"]),
                          "expect_speaker_any": r.get("expect_speaker_any", []), "expect_message_contains": "",
                          "voice": r.get("attribution", "?"), "group": "real-" + ("native" if r.get("speaker_native", True) else "accent"),
                          "condition": "clean", "source": "real", "accent": r.get("accent", "")})
    if a.only:
        keep = set(a.only.split(","))
        items = [c for c in items if keep & {c.get("category"), c["group"], c["condition"], c["source"]}]

    rng = np.random.default_rng(a.seed)
    babble = [synth(t, v, cache) for t, v in [("Und dann hat er gesagt, dass wir morgen wieder kommen sollen.", "Anna"),
                                              ("Nein, das glaube ich nicht, das war doch ganz anders.", "Rocko (German (Germany))"),
                                              ("Kannst du mal eben die Tasche halten, ich suche den Schlüssel.", "Sandy (German (Germany))")]]
    results = []
    t_start = time.time()
    for n, c in enumerate(items, 1):
        res = {k: c.get(k) for k in ("id", "category", "side", "group", "voice", "condition", "source")}
        res["expect"] = c.get("expect_speaker_any", [])
        ideal = identify(c["text"], ("Jonas", "Anna"), llm, a.llm_model, side=c.get("side", "door"))
        res["text_speaker"] = ideal.speaker
        res["text_ok"] = speaker_ok(res["expect"], ideal.speaker)
        if not a.text_only:
            if c["source"] == "real":
                x = read_wav(Path(c["file"]))
                x = degrade(x, "clean", rng, babble)
            else:
                x = degrade(synth(c["say"], c["voice"], cache), c["condition"], rng, babble)
            audio = wav_bytes(x)
            key = hashlib.sha1(audio + f"|{a.language}|{a.prompt}".encode()).hexdigest()
            if key not in tcache:
                t0 = time.time()
                heard = whisper(a.whisper_url, audio, a.language, a.prompt)
                if a.prompt and prompt_echo(heard):   # same fallback as aikos_transcriber/worker.py
                    heard = whisper(a.whisper_url, audio, a.language, "")
                tcache[key] = {"text": heard, "s": round(time.time() - t0, 2)}
            heard = strip_captions(tcache[key]["text"])
            res["heard"] = heard
            res["whisper_s"] = tcache[key]["s"]
            res["recall"] = round(recall(c["say"], heard), 3)
            t0 = time.time()
            who = identify(heard, ("Jonas", "Anna"), llm, a.llm_model, side=c.get("side", "door")) if not is_noise(heard) else None
            res["id_s"] = round(time.time() - t0, 2)
            res["speaker"] = who.speaker if who else ""
            res["method"] = who.method if who else "noise"
            res["message"] = who.message if who else ""
            res["ok"] = speaker_ok(res["expect"], res["speaker"])
            res["msg_ok"] = (c.get("expect_message_contains", "").lower() in res["message"].lower()) if c.get("expect_message_contains") else None
        results.append(res)
        if n % 25 == 0:
            print(f"  {n}/{len(items)} … {time.time() - t_start:.0f} s", file=sys.stderr, flush=True)
            tcache_p.write_text(json.dumps(tcache, ensure_ascii=False), encoding="utf-8")
    tcache_p.write_text(json.dumps(tcache, ensure_ascii=False), encoding="utf-8")
    (a.out / f"results_{a.tag}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    report(results, a)


def report(results, a):
    def rate(rs, k):
        v = [r[k] for r in rs if r.get(k) is not None]
        return f"{100 * sum(v) / len(v):5.1f} % ({sum(v)}/{len(v)})" if v else "   –"

    audio = not a.text_only
    print(f"\n=== {a.tag}: {len(results)} cases · LLM {'off' if a.no_llm else a.llm_model} · prompt {'yes' if a.prompt else 'no'} ===")
    print(f"text-only recognition : {rate(results, 'text_ok')}")
    if audio:
        print(f"end-to-end recognition: {rate(results, 'ok')}")
        rc = [r["recall"] for r in results]
        print(f"completeness          : mean {100 * np.mean(rc):.1f} %, ≥ 90 % words in {100 * np.mean([x >= 0.9 for x in rc]):.1f} % of cases")
        idt = [r["id_s"] for r in results]
        print(f"detector time         : median {np.median(idt):.2f} s, max {max(idt):.2f} s")
    for key in ("group", "condition", "category", "side"):
        groups = collections.defaultdict(list)
        for r in results:
            groups[r.get(key)].append(r)
        print(f"-- by {key}: " + " · ".join(f"{g}: {rate(rs, 'ok' if audio else 'text_ok').split(' (')[0].strip()} ({len(rs)})"
                                         for g, rs in sorted(groups.items(), key=lambda kv: str(kv[0]))))
    fails = [r for r in results if not r.get("ok" if audio else "text_ok")]
    print(f"-- {len(fails)} failures:")
    for r in fails:
        exp = " | ".join("+".join(alt) for alt in r["expect"]) or "∅"
        if audio:
            print(f"  {r['id']:<12} [{r['group']}/{r['condition']}] expect {exp!r} got {r['speaker']!r} ({r['method']}) "
                  f"text-only {r['text_speaker']!r} · heard “{r['heard']}”")
        else:
            print(f"  {r['id']:<12} expect {exp!r} got {r['text_speaker']!r}")


if __name__ == "__main__":
    main()
