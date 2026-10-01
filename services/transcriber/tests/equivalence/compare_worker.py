"""Equivalence check: `python -m aikos_transcriber.worker` must send Home Assistant exactly what roomkey
tools/transcribe_publish.py sends, for the same recordings and the same answers from Whisper and the LLM.

    ROOMKEY_TOOLS=<path to roomkey/tools at the reference commit> python tests/equivalence/compare_worker.py

Fake Whisper, LLM and Home Assistant servers run on localhost; every scenario runs through the old script and the new
worker; the recorded HA calls are compared (timestamps and timings removed). Exit code 1 on a difference.
"""
import array
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve()
PKG_ROOT = HERE.parents[2]                                    # services/transcriber
OLD = Path(os.environ["ROOMKEY_TOOLS"])
RATE = 16000

# what the fake Whisper "hears", by recording name: (German pass text, verbose result for the language pass)
HEARD = {
    "room_marie": ("Hier ist Marie, ich komme gleich runter.", {"text": "Hier ist Marie, ich komme gleich runter.",
                                                               "language_probabilities": {"de": 0.97, "en": 0.02}}),
    "door_dhl": ("Guten Tag, Paketdienst von DHL, ich habe ein Paket für Sie.",
                 {"text": "Guten Tag, Paketdienst von DHL, ich habe ein Paket für Sie.", "language_probabilities": {"de": 0.99}}),
    "door_test": ("Guten Tag, hier ist der Schornsteinfeger.", {"text": "Guten Tag, hier ist der Schornsteinfeger.",
                                                               "language_probabilities": {"de": 0.99}}),
    "door_noise": ("[Musik]", {"text": "[Musik]", "language_probabilities": {"de": 0.5}}),
    "door_english": ("Hello, this is Anna, I have a parcel for you.",
                     {"text": "Hello, this is Anna, I have a parcel for you.", "language_probabilities": {"en": 0.98, "de": 0.01}}),
    "door_echo": ("Ich komme gleich runter. Guten Tag, hier ist die Nachbarin.",
                  {"text": "Ich komme gleich runter. Guten Tag, hier ist die Nachbarin.", "language_probabilities": {"de": 0.99}}),
    "door_silent": ("Haustür-Sprechanlage.", {"text": "", "language_probabilities": {"de": 1.0}}),
}
calls = []                                                    # recorded HA calls of the current run
room_state = {"state": "2000-01-01T00:00:00+00:00", "attributes": {"text": "Ich komme gleich runter."}}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        raw = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/states":                         # key_for_ip
            self._send([{"entity_id": "sensor.aikos_roomkey_desk_ip_address", "state": "192.0.2.44",
                         "attributes": {"friendly_name": "aikos RoomKey Desk IP address"}}])
        elif self.path.startswith("/api/states/sensor.talk_transcript"):   # the echo reference
            self._send(room_state)
        else:
            self._send({})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/whisper"):
            name = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode().rsplit(".", 1)[0]
            key = next(k for k in HEARD if name.startswith(k))
            verbose = b"verbose_json" in body
            self._send(HEARD[key][1] if verbose else {"text": HEARD[key][0]})
        elif self.path == "/api/chat":                         # the LLM: translation, or "nobody" for the identity fallback
            req = json.loads(body)
            if req.get("format") == "json":
                self._send({"message": {"content": json.dumps({"speaker": "", "kind": "none", "role": ""})}})
            else:
                self._send({"message": {"content": "Hallo, hier ist Anna, ich habe ein Paket für Sie."}})
        else:
            calls.append((self.path, json.loads(body) if body else None))
            self._send({})


def tone_wav(path: Path, speech_s: float, quiet: bool = False):
    n_pad, n_speech = int(0.5 * RATE), int(speech_s * RATE)
    amp = 0 if quiet else 3000
    x = array.array("h", [0] * n_pad + [int(amp * math.sin(2 * math.pi * 300 * i / RATE)) for i in range(n_speech)] + [0] * n_pad)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(x.tobytes())


def normalise(call):
    path, body = call
    if isinstance(body, dict):
        body = json.loads(json.dumps(body))
        body.pop("state", None) if path.startswith("/api/states/") else None
        for d in (body, body.get("attributes", {}) if isinstance(body.get("attributes"), dict) else {}):
            for k in ("created", "transcribe_s"):
                d.pop(k, None)
    return path, body


def run(kind, wav, args, env):
    calls.clear()
    if kind == "old":
        cmd = [sys.executable, str(OLD / "transcribe_publish.py"), str(wav)] + args
        cwd = OLD
    else:
        cmd = [sys.executable, "-m", "aikos_transcriber.worker", str(wav)] + args
        cwd = PKG_ROOT
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    time.sleep(0.2)
    return [normalise(c) for c in calls], out.returncode


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    tmp = Path(tempfile.mkdtemp())
    token = tmp / "token"; token.write_text("t")
    activity = tmp / "room_active"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    common = ["--ha-url", base, "--token-file", str(token), "--whisper-url", base + "/whisper", "--llm-url", base,
              "--known-names", "Paul,Marie", "--test-sources", "127.0.0.1"]
    scenarios = [
        ("room_marie", ["--side", "room", "--source-ip", "192.0.2.44"], 1.2, False, None),
        ("door_dhl", ["--side", "door", "--source-ip", "192.0.2.62", "--activity-file", str(activity)], 1.5, False, None),
        ("door_test", ["--side", "door", "--source-ip", "127.0.0.1", "--activity-file", str(activity)], 1.2, False, None),
        ("door_noise", ["--side", "door", "--source-ip", "192.0.2.62"], 1.0, False, None),
        ("door_english", ["--side", "door", "--source-ip", "192.0.2.62"], 1.5, False, None),
        ("door_echo", ["--side", "door", "--source-ip", "192.0.2.62", "--activity-file", str(activity)], 2.0, False, "overlap"),
        ("door_silent", ["--side", "door", "--source-ip", "192.0.2.62"], 1.0, True, None),
    ]
    differences = 0
    for name, args, secs, quiet, echo in scenarios:
        results = {}
        for kind in ("old", "new"):
            wav = tmp / f"{name}_{kind}.wav"
            tone_wav(wav, secs, quiet)
            end = time.time()
            os.utime(wav, (end, end))
            if echo:                                           # a resident talked during this door audio
                activity.write_text(f"{end - secs:.3f}\n"); os.utime(activity, (end, end))
                room_state["state"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(end))
            elif activity.exists():
                activity.unlink()
            results[kind] = run(kind, wav, args + common, env)
        same = results["old"] == results["new"]
        differences += 0 if same else 1
        posted = [p for p, _ in results["new"][0]]
        print(f"{'SAME' if same else 'DIFFERENT'} {name}: {len(results['new'][0])} HA calls {posted}")
        if not same:
            print("  old:", json.dumps(results["old"], ensure_ascii=False)[:1500])
            print("  new:", json.dumps(results["new"], ensure_ascii=False)[:1500])
    shutil.rmtree(tmp, ignore_errors=True)
    srv.shutdown()
    print("ALL SAME" if not differences else f"{differences} DIFFERENT")
    sys.exit(1 if differences else 0)


if __name__ == "__main__":
    main()
