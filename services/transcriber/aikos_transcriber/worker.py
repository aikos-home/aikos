"""One utterance: speech? → Whisper → language → echo filter → who is speaking → Home Assistant.

    python -m aikos_transcriber.worker <wav> --side room|door --ha-url http://<ha>:8123 --token-file <file> \
        [--source-ip <sender>] [--whisper-url …] [--llm-url … | --no-llm] [--known-names Anna,Jonas] [--delete-wav]
        [--test-sources 127.0.0.1] [--activity-file <state dir>/room_active]

Started by the receiver once per utterance (its own process, so a crash here never stops the receiver).
Publishes sensor.talk_transcript (room side) / sensor.talk_transcript_door (door side): state = ISO timestamp,
attributes text, message, speaker, speaker_kind, speaker_role, speaker_org, speaker_method, urgent, side, device,
key_id, duration_s, language, language_name(_en), language_probability, text_original, model, created, source,
transcribe_s; plus the event aikos_talk_transcript. Test senders go to *_test entities and aikos_talk_transcript_test.
Utterances without words are not published. Local only: audio goes to the Whisper server, never to a cloud.
W3 (--mic-check): after each recording of at least 0.5 s the event aikos_mic_check (verdict ok | silent | clipping and the
numbers) goes to Home Assistant, after the text, also when nothing was said: a dead or overdriven mic is seen at once.
R28 (--translate-to-visitor, room side): when the call log says the visitor speaks another language, the German answer goes out
first as always; its translation into the visitor's language follows as an update (attributes text_visitor, visitor_language).

Part of the aikos transcriber (split from roomkey tools/transcribe_publish.py at d0d52b9, code unchanged)."""
from __future__ import annotations

import argparse
import atexit
import datetime as dt
import sys
import time
import wave
from pathlib import Path

from .audio import has_speech, voiced_frames
from .echo import drop_echo, is_household, resident_overlap_s, resident_talk, speech_outside_s
from .ha import ha, key_for_ip
from .mic import stats as mic_stats
from .identity import WHISPER_PROMPT, identify, is_noise, prompt_echo, strip_captions
from .translate import from_german, to_german
from .whisper import LANGUAGES, looks_german, spoken_language, whisper


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", type=Path)
    ap.add_argument("--ha-url", required=True)
    ap.add_argument("--token-file", type=Path, required=True)
    ap.add_argument("--whisper-url", default="http://127.0.0.1:6667/v1/audio/transcriptions")
    ap.add_argument("--language", default="de", help='"auto" guesses per clip — unreliable for 2–5 s of speech')
    ap.add_argument("--source-ip", default="")
    ap.add_argument("--side", choices=("room", "door"), default="room", help="who spoke: a RoomKey (room) or the door")
    ap.add_argument("--entity", default="", help="default: sensor.talk_transcript (room) / sensor.talk_transcript_door (door)")
    ap.add_argument("--llm-url", default="http://127.0.0.1:11434", help="local Ollama, only asked when the rules find nobody")
    ap.add_argument("--llm-model", default="qwen3:8b")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-prompt", action="store_true", help="don't give Whisper the doorstep vocabulary hint")
    ap.add_argument("--known-names", default="", help="comma-separated household names (spelling as shown)")
    ap.add_argument("--delete-wav", action="store_true", help="delete the recording when done (privacy; for the service)")
    ap.add_argument("--echo-ref", default="sensor.talk_transcript", help="door side: the room transcript to filter echoes against")
    ap.add_argument("--activity-file", default="", help="door side: touched by the room receiver while a resident talks")
    ap.add_argument("--test-sources", default="", help="comma-separated IPs of test senders → *_test entities and event")
    ap.add_argument("--translate-to-visitor", action="store_true",
                    help="room side, R28: translate the answer into the visitor's language (from the call log), after the German text")
    ap.add_argument("--call-log", default="sensor.aikos_call_log", help="where the visitor's language is (visitor_language)")
    ap.add_argument("--mic-check", action="store_true", help="W3: report the mic's health of every recording (event aikos_mic_check)")
    a = ap.parse_args()
    entity = a.entity or ("sensor.talk_transcript" if a.side == "room" else "sensor.talk_transcript_door")
    test = a.source_ip in {s.strip() for s in a.test_sources.split(",") if s.strip()}
    sfx = "_test" if test else ""                      # tests never write into live entities (qualitaet.md §3.8)
    entity, event = entity + sfx, "aikos_talk_transcript" + sfx
    echo_ref, activity_file = a.echo_ref + sfx, a.activity_file + sfx if a.activity_file else ""
    call_log = a.call_log + sfx
    token = a.token_file.expanduser().read_text().strip()

    with wave.open(str(a.wav)) as w:
        duration = w.getnframes() / w.getframerate()
        pcm = w.readframes(w.getnframes()) if a.mic_check else b""
    if a.mic_check:
        mic = mic_stats(pcm)
        if mic is not None:                       # reported at exit: after the text, and also when nothing is published
            atexit.register(report_mic, a.ha_url, token, "aikos_mic_check" + sfx, a.side, a.source_ip, mic)
    t0 = time.time()
    names = [n.strip() for n in a.known_names.split(",") if n.strip()]
    # household names as a plain list (not "Hier ist Anna." — on silence Whisper answers with such a sentence)
    prompt = "" if a.no_prompt else WHISPER_PROMPT + (" Namen: " + ", ".join(names) + "." if names else "")
    if not has_speech(a.wav):                     # key pressed, nothing said: never let Whisper "hear" its hint
        print(f"· {a.side}: no speech in {a.wav.name} (level), not transcribed", flush=True)
        return
    if a.side == "door" and activity_file:
        # The door mic hears a resident (through the door speaker, or directly when the devices sit close): Whisper
        # garbles such an echo, so the words don't match the resident's. Its timing does: all of its speech lies in the
        # resident's talk. Then it is no visitor, whatever Whisper would make of it (live test 01.10. 18:58).
        end = a.wav.stat().st_mtime
        began, last = resident_talk(activity_file)
        if began and resident_overlap_s(activity_file, (end - duration, end)) >= 0.5:
            with wave.open(str(a.wav)) as w:
                outside = speech_outside_s(voiced_frames(w.readframes(w.getnframes())), end - duration, began, last)
            if outside < 0.3:
                print(f"· door: all speech in {a.wav.name} lies in a resident's talk: an echo, not transcribed", flush=True)
                return
    # Pass 1: German text for the screens (for foreign speech Whisper translates it into German on the way).
    # It is published at once; pass 2 (which language was spoken, and its words) follows ~1 s later under the same
    # timestamp. The Whisper server works one request at a time, so waiting for both would delay the text by ~1 s.
    text = whisper(a.whisper_url, a.wav, a.language, prompt)
    if not a.no_prompt and prompt_echo(text, prompt):  # unclear audio: Whisper repeated its hint → ask again without it
        text = whisper(a.whisper_url, a.wav, a.language, "")
    took = time.time() - t0
    if is_noise(text):
        print(f"· {a.side}: no speech in {a.wav.name} (“{text}”), not published", flush=True)
        return
    text = strip_captions(text)
    detected, lang, lang_p, original = None, "", None, ""
    if not looks_german(text):
        # Not German (Whisper translates many languages on the way, but not e.g. English): find out which language,
        # then let the local LLM translate. Text and original go out together — no English-then-German flicker.
        detected = whisper(a.whisper_url, a.wav, "auto", "", True)
        probs = detected.get("language_probabilities") or {"de": 1.0}
        lang, lang_p = max(probs.items(), key=lambda kv: kv[1])
        if lang != "de":
            original = strip_captions(detected.get("text", "")) or text
            text = (to_german(original, LANGUAGES.get(lang, (lang,))[0], a.llm_url, a.llm_model) if not a.no_llm else "") or text
        took = time.time() - t0
    door_span = (0.0, 0.0)
    if a.side == "door":
        end = a.wav.stat().st_mtime
        door_span = (end - duration, end)
        text = drop_echo(text, a.ha_url, token, door_span, activity_file, ref_entity=echo_ref)
        if not text:
            print(f"· door: only an echo of the resident in {a.wav.name}, not published", flush=True)
            return
    who = identify(text, names,
                   "" if a.no_llm else a.llm_url, a.llm_model, side=a.side)
    if a.side == "door" and who.kind == "name" and is_household(who.name, names) and \
            resident_overlap_s(activity_file, door_span) >= 0.5:
        # the door mic heard a resident (crosstalk, or the door speaker) and no room transcript filtered it, e.g. because
        # the key's mic sent silence: never show the resident's own words as a visitor (system test W1, 01.10.)
        print(f"· door: \"{who.name}\" while a resident talked: the resident's own words, not published", flush=True)
        return
    device, key_id = key_for_ip(a.ha_url, token, a.source_ip) if a.source_ip else (None, None)
    KNOWN_DEVICE[a.source_ip] = (device, key_id)                    # W3's report needs no second /api/states fetch
    created = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    data = {"text": text, "message": who.message, "speaker": who.speaker, "speaker_kind": who.kind,
            "speaker_role": who.vtype, "speaker_org": who.org, "speaker_method": who.method, "urgent": who.urgent,
            "side": a.side,
            "device": device or "unknown", "key_id": key_id or "unknown", "duration_s": round(duration, 1),
            "language": lang, "language_name": LANGUAGES.get(lang, (lang,))[0] if lang else "",
            "language_name_en": LANGUAGES.get(lang, (None, lang))[1] if lang else "",
            "language_probability": round(lang_p, 2) if lang_p is not None else None,
            "text_original": original, "model": "whisper.cpp large-v3 (local)", "created": created,
            "source": "roomkey-test", "transcribe_s": round(took, 1)}
    name = ("Talk transcript (TEST)" if a.side == "room" else "Talk transcript door (TEST)") + (" test senders" if test else "")
    extra = {"friendly_name": name, "icon": "mdi:text-box-outline"}
    ha(a.ha_url, token, "POST", f"/api/states/{entity}", {"state": created, "attributes": {**data, **extra}})
    shown = time.time() - t0
    print(f"✎ {a.side} {device or '?'}: “{text}”  → speaker “{who.speaker or '–'}” ({who.method or 'none'}), "
          f"message “{who.message}”  ({duration:.1f} s audio, in HA after {shown:.1f} s) → {entity}", flush=True)
    if a.translate_to_visitor and a.side == "room" and detected is None and not a.no_llm:
        # R28: only after the German text is out, and only in a call whose visitor speaks another language
        to_lang = visitor_language(a.ha_url, token, call_log)
        if to_lang:
            source = who.message or text
            translated = from_german(source, LANGUAGES.get(to_lang, (to_lang,))[0], a.llm_url, a.llm_model)
            if translated and same_words(translated, source):            # the LLM gave the German back: nothing to send
                print(f"  for the visitor ({to_lang}): the LLM returned the German unchanged, no update", flush=True)
                translated = ""
            if translated:
                data.update({"text_visitor": translated, "visitor_language": to_lang})
                ha(a.ha_url, token, "POST", f"/api/states/{entity}", {"state": created, "attributes": {**data, **extra}})
                print(f"  for the visitor ({to_lang}) after {time.time() - t0:.1f} s: “{translated}”", flush=True)
    if detected is not None:                               # foreign: everything went out together already
        ha(a.ha_url, token, "POST", f"/api/events/{event}", data)
        print(f"  language {lang} ({lang_p:.2f}), translated: “{original}”", flush=True)
        return
    try:                                                   # pass 2: the language is a bonus, the text is out already
        detected = whisper(a.whisper_url, a.wav, "auto", "", True)
    except Exception:
        detected = {}
    lang, lang_p = spoken_language(detected)
    if lang == "en":
        lang = "de"                                        # the German pass WAS German: a short German clip taken for English
    data.update({"language": lang, "language_name": LANGUAGES.get(lang, (lang,))[0],
                 "language_name_en": LANGUAGES.get(lang, (None, lang))[1], "language_probability": round(lang_p, 2),
                 "text_original": strip_captions(detected.get("text", "")) if lang != "de" else ""})
    ha(a.ha_url, token, "POST", f"/api/states/{entity}", {"state": created, "attributes": {**data, **extra}})
    ha(a.ha_url, token, "POST", f"/api/events/{event}", data)
    print(f"  language {lang} ({lang_p:.2f}) after {time.time() - t0:.1f} s"
          + (f": “{data['text_original']}”" if lang != "de" else ""), flush=True)

KNOWN_DEVICE: dict = {}                                                 # source IP → (device, key_id), set by the main path


def report_mic(url: str, token: str, event: str, side: str, source_ip: str, mic) -> None:
    """W3: one event per recording with the mic's verdict; never fails the worker."""
    try:
        if source_ip in KNOWN_DEVICE:
            device, key_id = KNOWN_DEVICE[source_ip]
        else:
            device, key_id = key_for_ip(url, token, source_ip) if source_ip else (None, None)
        data = {"side": side, "device": device or "unknown", "key_id": key_id or "unknown", "source": source_ip,
                "created": dt.datetime.now().astimezone().isoformat(timespec="seconds"), **mic.as_dict()}
        ha(url, token, "POST", f"/api/events/{event}", data)
        if mic.verdict != "ok":
            print(f"⚠ mic {device or source_ip}: {mic.verdict} ({mic.as_dict()})", flush=True)
    except Exception as exc:
        print(f"mic report failed: {exc}", file=sys.stderr, flush=True)


def same_words(a: str, b: str) -> bool:
    """True if two sentences have the same words (case, punctuation and spacing aside)."""
    norm = lambda x: " ".join("".join(ch for ch in x.lower() if ch.isalnum() or ch.isspace()).split())
    return norm(a) == norm(b)


def visitor_language(url: str, token: str, call_log: str) -> str:
    """The call's visitor language from the aikos call log ("" = German, unknown, or no call log)."""
    try:
        lang = (ha(url, token, "GET", f"/api/states/{call_log}") or {}).get("attributes", {}).get("visitor_language") or ""
    except Exception:
        return ""
    return "" if lang == "de" else str(lang)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never crash the recorder that called us
        print(f"transcribe_publish failed: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    finally:
        if "--delete-wav" in sys.argv[1:]:
            wav = next((Path(x) for x in sys.argv[1:] if x.endswith(".wav")), None)
            if wav:
                wav.unlink(missing_ok=True)
