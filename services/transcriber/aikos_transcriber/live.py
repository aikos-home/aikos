"""Live text while somebody is still talking (partials, re-transcribed about every 0.3 s).

Part of the aikos transcriber (split from roomkey tools/talk_live.py at d0d52b9, code unchanged)."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.request
import uuid

from .audio import RATE, has_speech_pcm, voiced_frames, wav_bytes
from .echo import is_household, resident_talk, speech_outside_s, strip_echo
from .identity import WHISPER_PROMPT, by_rules, classify, clean, is_noise, prompt_echo, strip_captions


class Live:
    def __init__(self, ha_url: str, token: str, entity: str, side: str, whisper_url: str, names=(), interval: float = 0.3,
                 quiet_file: str = "", echo_ref: str = "sensor.talk_transcript"):
        self.ha_url, self.token, self.entity, self.side = ha_url.rstrip("/"), token, entity, side
        self.whisper_url, self.names, self.interval = whisper_url, list(names), interval
        self.prompt = WHISPER_PROMPT + (" Namen: " + ", ".join(self.names) + "." if self.names else "")
        self.quiet_file = quiet_file   # touched by the room receiver while a RoomKey talks: no door partials then (echo)
        self.echo_ref = echo_ref       # after that, the resident's transcript: its echo is removed from the partials
        self.rec = None
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    # ── called from the recorder (main thread) ──
    def start(self, rec, test: bool = False):
        """A new utterance. test = from a test sender: published to <entity>_test, compared with test residents only."""
        sfx = "_test" if test else ""
        with self.lock:
            self.rec, self.text, self.speaker, self.seq, self.done_len = rec, "", "", 0, 0
            self.cur_entity, self.cur_ref = self.entity + sfx, self.echo_ref + sfx
            self.cur_quiet = self.quiet_file + sfx if self.quiet_file else ""
            self.vtype, self.urgent, self.warned, self.overlap = "", False, False, False
            self.started = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    def stop(self, rec):
        with self.lock:
            if self.rec is not rec:
                return
            self.rec = None
            text, speaker, started, seq, entity = self.text, self.speaker, self.started, self.seq, self.cur_entity
        if text:
            self._publish(entity, started, text, speaker, True, seq + 1)

    # ── worker ──
    def _run(self):
        while True:
            time.sleep(self.interval)
            with self.lock:
                rec = self.rec
                if rec is None:
                    continue
                pcm = bytes(rec.pcm)
                started, done_len, entity, quiet, ref = self.started, self.done_len, self.cur_entity, self.cur_quiet, self.cur_ref
            if len(pcm) - done_len < int(0.3 * RATE) * 2 or not has_speech_pcm(pcm):
                continue
            began, active = resident_talk(quiet) if quiet else (0.0, 0.0)
            if time.time() - active < 0.8:
                self.overlap = True             # a resident is talking: the door mic hears the door speaker
                continue
            said = None
            if self.overlap:                    # this utterance overlapped the resident: wait for the resident's text
                start = time.time() - len(pcm) / (2 * RATE)      # the recording runs in real time
                if began and speech_outside_s(voiced_frames(pcm), start, began, active) < 0.3:
                    continue                    # all of it lies in the resident's talk: an echo, no partials
                said = self._resident_text(ref, began, active)
                if said is None:
                    continue
            try:
                text = self._whisper(wav_bytes(pcm))
            except Exception as exc:
                if not getattr(self, "warned", False):
                    print(f"  live: Whisper failed ({exc})", flush=True)
                    self.warned = True
                continue
            text = strip_captions(text)
            if said:
                text = strip_echo(text, said)
            if not text or is_noise(text) or prompt_echo(text, self.prompt):
                continue
            who = classify(by_rules(text, self.names, self.side), clean(text), self.side)
            if self.overlap and who.kind == "name" and is_household(who.name, self.names):
                continue                        # the resident's own words heard at the door (W1): no visitor partials
            with self.lock:
                if self.rec is not rec:
                    continue                    # a new utterance began meanwhile: this text is stale
                if text == self.text:
                    self.done_len = len(pcm)
                    continue
                self.text, self.done_len, self.seq = text, len(pcm), self.seq + 1
                self.speaker = who.speaker or self.speaker
                self.vtype = who.vtype or getattr(self, "vtype", "")
                self.urgent = who.urgent or getattr(self, "urgent", False)
                speaker, seq = self.speaker, self.seq
            self._publish(entity, started, text, speaker, False, seq)

    def _resident_text(self, ref: str, began: float, active: float):
        """The resident's transcript of the talk that began at `began`; None while it is still being made."""
        req = urllib.request.Request(f"{self.ha_url}/api/states/{ref}", headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                st = json.loads(r.read())
            made = dt.datetime.fromisoformat(st["state"]).timestamp()
        except Exception:
            return ""                           # no reference: show the partials unfiltered (the final text is filtered)
        if made < began - 0.2 and time.time() - active < 5:
            return None
        return st["attributes"].get("text", "") if time.time() - made < 30 else ""

    def _whisper(self, audio: bytes) -> str:
        boundary = uuid.uuid4().hex
        fields = [("response_format", "json"), ("language", "de"), ("temperature", "0"), ("prompt", self.prompt)]
        body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields)
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="live.wav"\r\n'
                 "Content-Type: audio/wav\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.whisper_url, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return " ".join(json.loads(r.read())["text"].split())

    def _publish(self, entity: str, started: str, text: str, speaker: str, final: bool, seq: int):
        body = {"state": started, "attributes": {
            "text": text, "speaker": speaker, "speaker_role": getattr(self, "vtype", ""), "urgent": getattr(self, "urgent", False),
            "final": final, "side": self.side, "seq": seq,
            "updated": dt.datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "friendly_name": "Talk live " + self.side + (" (test senders)" if entity.endswith("_test") else " (TEST)"),
            "icon": "mdi:text-recognition"}}
        req = urllib.request.Request(f"{self.ha_url}/api/states/{entity}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
            print(f"  ⋯ live {'final' if final else seq}: “{text}”" + (f" [{speaker}]" if speaker else ""), flush=True)
        except Exception as exc:
            print(f"  live publish failed: {exc}", flush=True)
