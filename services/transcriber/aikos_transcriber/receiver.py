"""RTP receiver: one recording per utterance, handed to the worker (python -m aikos_transcriber.worker).

Part of the aikos transcriber (split from roomkey tools/rtp_recorder.py at d0d52b9, code unchanged)."""
from __future__ import annotations

import argparse
import collections
import math
import os
import shlex
import socket
import subprocess
import struct
import sys
import threading
import time
import wave
from pathlib import Path

from .ha import ha, key_for_ip
from .mic import SILENT, SilenceWatch

RATE, PT_L16, PT_CN = 16000, 96, 13   # PT 13 = comfort noise (RFC 3389): the sender stopped talking


class VoiceGate:
    """Speech from levels alone, as the door's own detector does it (aikos_voice level.h VoiceGate, same constants): a
    20 ms packet counts when its smoothed level is 11 dB above the floor (5th percentile of the last 1.5 s, not the
    quietest packet) for at least a third of the last 120 ms. Music beats and clicks of a few packets don't count; the
    plain per-packet threshold took them for speech, so a pause in a noisy room never came and the door segment ran
    to --max-s (04.10. 20:10: speech ended 08.6, text at 22.1)."""
    VOICE_DB, MIN_DB, WINDOW_MS, PERCENTILE, SKIP, SUSTAIN_MS, N = 11.0, -75.0, 1500, 0.05, 2, 120, 96

    def __init__(self):
        self.hist = collections.deque(maxlen=self.N)                     # (ms, dB, loud)
        self.smooth = -120.0

    def note(self, db: float, now_ms: float) -> bool:
        if db < -100.0:                                                  # muted / digital silence: no information
            return False
        win = [d for m, d, _ in self.hist if now_ms - m < self.WINDOW_MS] + [db]
        n = len(win)
        k = max(int(self.PERCENTILE * (n - 1)), self.SKIP if n > 8 else 0)
        floor = sorted(win)[k]
        self.smooth = db if self.smooth < -100.0 else self.smooth * 0.7 + db * 0.3
        loud = self.smooth > floor + self.VOICE_DB and db > self.MIN_DB
        self.hist.append((now_ms, db, loud))
        recent = [l for m, _, l in self.hist if now_ms - m < self.SUSTAIN_MS]
        return loud and n > 8 and len(recent) >= 3 and 3 * sum(recent) >= len(recent)


class Recording:
    def __init__(self, out: Path, src):
        out.mkdir(parents=True, exist_ok=True)
        stem = f"roomkey_{time.strftime('%Y%m%d_%H%M%S')}_{src[0].replace('.', '-')}"
        self.path, n = out / f"{stem}.wav", 2
        while self.path.exists():   # a second utterance in the same second (e.g. after --max-s) must not overwrite the first
            self.path, n = out / f"{stem}_{n}.wav", n + 1
        self.wav = wave.open(str(self.path), "wb")
        self.wav.setnchannels(1); self.wav.setsampwidth(2); self.wav.setframerate(RATE)
        self.src, self.t0, self.last = src, time.time(), time.time()
        self.voiced_at = 0          # sample count at the last loud packet (RTP time, not wall-clock)
        self.speech_at = 0          # sample count at the last sustained speech (VoiceGate, --split-on-silence)
        self.voiced_pkts = 0
        self.pkts = self.lost = self.samples = 0
        self.pcm = bytearray()      # the utterance so far (16-bit LE), for --live
        self.seq = None
        self.sumsq = 0.0
        self.peak = 0
        print(f"● recording from {src[0]}:{src[1]} → {self.path}", flush=True)

    @staticmethod
    def level_db(payload) -> float:
        n = len(payload) // 2
        pcm = struct.unpack(f">{n}h", payload[: n * 2])
        return 20 * math.log10(math.sqrt(sum(v * v for v in pcm) / max(1, n)) / 32768 + 1e-9)

    def add(self, seq, payload, voiced=True):
        if self.seq is not None:
            gap = (seq - self.seq - 1) & 0xFFFF
            if 0 < gap < 1000:
                self.lost += gap
                fill = min(gap, 50)                                  # keep the timeline, but never add > 1 s
                self.wav.writeframes(b"\x00\x00" * (320 * fill))
                self.pcm += b"\x00\x00" * (320 * fill)
                self.samples += 320 * fill
        self.seq = seq
        n = len(payload) // 2
        pcm = struct.unpack(f">{n}h", payload[: n * 2])            # L16 = big-endian
        le = struct.pack(f"<{n}h", *pcm)
        self.wav.writeframes(le)
        self.pcm += le
        self.sumsq += sum(v * v for v in pcm)
        self.peak = max(self.peak, max((abs(v) for v in pcm), default=0))
        self.pkts += 1
        self.samples += n
        self.last = time.time()
        if voiced:
            self.voiced_at = self.samples
            self.voiced_pkts += 1

    def quiet_s(self) -> float:
        return (self.samples - self.voiced_at) / RATE

    def speech_quiet_s(self) -> float:
        return (self.samples - self.speech_at) / RATE

    def close(self, exec_tpl=None, min_voiced=0):
        self.wav.close()
        if self.voiced_pkts < min_voiced:        # a click or a cough, not an utterance: nothing to transcribe
            print(f"· dropped {self.path.name}: only {self.voiced_pkts * 20} ms above the noise", flush=True)
            self.path.unlink(missing_ok=True)
            return
        dur = self.samples / RATE
        rms = math.sqrt(self.sumsq / max(1, self.samples)) / 32768
        db = 20 * math.log10(rms + 1e-9)
        pk = 20 * math.log10(self.peak / 32768 + 1e-9)
        print(f"■ saved {self.path.name}: {dur:.1f} s, {self.pkts} packets, {self.lost} lost, "
              f"level {db:.1f} dBFS (peak {pk:.1f})", flush=True)
        if exec_tpl:   # e.g. transcribe + publish; runs in the background, never blocks recording
            cmd = exec_tpl.replace("{wav}", shlex.quote(str(self.path))).replace("{src}", self.src[0])
            subprocess.Popen(cmd, shell=True)


def report_silence(url: str, token: str, event: str, source_ip: str, seconds: float) -> None:
    """W3: the door stream carried only zeros (a dead mic). Same event as the worker's per-recording check; never raises."""
    try:
        device, key_id = key_for_ip(url, token, source_ip)
        ha(url, token, "POST", f"/api/events/{event}", {
            "side": "door", "device": device or "unknown", "key_id": key_id or "unknown", "source": source_ip,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "verdict": SILENT, "duration_s": round(seconds, 1), "zero_ratio": 1.0,
            "clip_ratio": 0.0, "peak_db": -120.0, "rms_db": -120.0, "origin": "receiver"})
    except Exception as exc:
        print(f"mic report failed: {exc}", file=sys.stderr, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=5006)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "recordings")
    ap.add_argument("--exec", dest="exec_tpl", default=None,
                    help='command run after each saved recording; {wav} and {src} are replaced')
    ap.add_argument("--gap-s", type=float, default=1.0, help="no packets for this long = end of a stream")
    ap.add_argument("--on-start", default=None, help="command run when a recording starts (e.g. wake up a local LLM)")
    ap.add_argument("--split-on-silence", action="store_true", help="cut a continuous stream into utterances")
    ap.add_argument("--vad-db", type=float, default=-50.0, help="speech is never quieter than this (dBFS)")
    ap.add_argument("--silence-s", type=float, default=1.5)
    ap.add_argument("--max-s", type=float, default=15.0)
    ap.add_argument("--live", default="", metavar="ENTITY", help="publish partial text while talking (tools/talk_live.py)")
    ap.add_argument("--live-side", default="door")
    ap.add_argument("--ha-url", default="")
    ap.add_argument("--token-file", type=Path)
    ap.add_argument("--whisper-url", default="http://127.0.0.1:6667/v1/audio/transcriptions")
    ap.add_argument("--known-names", default="")
    ap.add_argument("--activity-file", default="", help="touched while audio arrives (room side: tells the door side 'a resident talks')")
    ap.add_argument("--live-quiet-file", default="", help="no live partials while this file was touched < 0.8 s ago")
    ap.add_argument("--test-sources", default="", help="comma-separated IPs of test senders: their activity and live text "
                                                        "go to *_test files/entities, never into live ones")
    ap.add_argument("--mic-check", action="store_true",
                    help="W3, door side (--split-on-silence): report a mic that sends only digital silence (event aikos_mic_check)")
    ap.add_argument("--mic-silence-s", type=float, default=10.0, help="W3: seconds of unbroken digital silence before reporting")
    a = ap.parse_args(argv)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", a.port))
    sock.settimeout(0.2)
    print(f"listening for RTP/L16 16 kHz on UDP {a.port}, saving to {a.out}", flush=True)
    live = None
    if a.live:
        from .live import Live
        live = Live(a.ha_url, a.token_file.expanduser().read_text().strip(), a.live, a.live_side, a.whisper_url,
                    [n.strip() for n in a.known_names.split(",") if n.strip()], quiet_file=a.live_quiet_file)
    test_ips = {s.strip() for s in a.test_sources.split(",") if s.strip()}
    watch = SilenceWatch(a.mic_silence_s) if a.mic_check and a.split_on_silence and a.ha_url and a.token_file else None
    ha_token = a.token_file.expanduser().read_text().strip() if watch else ""

    def resident_talking(src) -> bool:                                  # the door may mute its mic while its speaker plays
        if not a.live_quiet_file:
            return False
        try:
            return time.time() - os.stat(a.live_quiet_file + ("_test" if src[0] in test_ips else "")).st_mtime < 1.0
        except OSError:
            return False
    last_touch: dict = {}

    def activity(src) -> str:                                            # a test sender never marks a real resident
        return a.activity_file + ("_test" if src[0] in test_ips else "") if a.activity_file else ""

    def finish(rec, **kw):
        if live:
            live.stop(rec)
        rec.close(a.exec_tpl, **kw)

    # Door side (voice v2, --split-on-silence): a resident taking the turn ends the visitor's utterance at once. Turn gaps at
    # a door are often shorter than --silence-s, and what follows is the resident's voice from the door speaker, which kept
    # the segment running to --max-s: the visitor's words came 15 s late and with the resident's echo in them (04.10.).
    # The room side writes the resident's start time into the activity file (= this side's --live-quiet-file).
    turn_file: dict = {}                                                 # quiet file → (mtime, start time)
    cut_for: dict = {}                                                   # sender → the resident start that already cut it

    def resident_began(src) -> float:
        if not a.live_quiet_file:
            return 0.0
        qf = a.live_quiet_file + ("_test" if src[0] in test_ips else "")
        try:
            mtime = os.stat(qf).st_mtime
        except OSError:
            return 0.0
        cached = turn_file.get(qf)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            began = float(Path(qf).read_text().split()[0])
        except (OSError, ValueError, IndexError):
            began = 0.0
        turn_file[qf] = (mtime, began)
        return began

    recs: dict = {}                                                      # sender → Recording
    preroll = collections.defaultdict(lambda: collections.deque(maxlen=15))   # 0.3 s before speech starts
    levels = collections.defaultdict(lambda: collections.deque(maxlen=250))   # last 5 s of packet levels
    gates = collections.defaultdict(VoiceGate)                          # sender → speech detector (cut decision)
    gate_ms = collections.defaultdict(float)                            # sender → its stream time (RTP, 20 ms/packet)
    while True:
        try:
            data, src = sock.recvfrom(2048)
        except socket.timeout:
            data = None
        for k in [k for k, r in recs.items() if time.time() - r.last > a.gap_s]:
            finish(recs.pop(k))
        if data and len(data) >= 12 and data[0] >> 6 == 2 and data[1] & 0x7F == PT_CN and src in recs:
            finish(recs.pop(src), min_voiced=15 if a.split_on_silence else 0)   # button released: done
            continue
        if not data or len(data) <= 12 or data[0] >> 6 != 2 or data[1] & 0x7F != PT_L16:
            continue                                                     # ≤ 12 bytes = keepalive
        act = activity(src)
        if act and time.time() - last_touch.get(act, 0.0) > 0.25:
            Path(act).touch()
            last_touch[act] = time.time()
        hdr = 12 + 4 * (data[0] & 0x0F)
        seq = struct.unpack(">H", data[2:4])[0]
        payload = data[hdr:]
        voiced = speech = True
        if a.split_on_silence:
            db = Recording.level_db(payload)
            lv = levels[src]
            lv.append(db)
            floor = sorted(lv)[len(lv) // 10]
            voiced = db > max(a.vad_db, floor + 10.0) and len(lv) > 5   # starts a recording (with its pre-roll)
            gate_ms[src] += (len(payload) // 2) / 16.0
            speech = gates[src].note(db, gate_ms[src])                  # decides where it ends
            if watch is not None:
                silent_s = watch.note(src, db, time.time(), excused=resident_talking(src))
                if silent_s:
                    event = "aikos_mic_check" + ("_test" if src[0] in test_ips else "")
                    print(f"⚠ mic {src[0]}: {silent_s:.0f} s of digital silence on the door stream", flush=True)
                    threading.Thread(target=report_silence, args=(a.ha_url, ha_token, event, src[0], silent_s), daemon=True).start()
        rec = recs.get(src)
        if rec is None:
            if not (voiced and speech):                                  # split: only sustained speech starts one
                preroll[src].append((seq, payload))
                continue
            rec = recs[src] = Recording(a.out, src)
            if act:
                Path(act).write_text(f"{time.time():.3f}\n")              # when this resident began (see talk_live)
            if live:
                live.start(rec, test=src[0] in test_ips)
            if a.on_start:
                subprocess.Popen(a.on_start, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for pseq, pp in preroll.pop(src, ()):
                rec.add(pseq, pp, voiced=False)
            rec.speech_at = rec.samples                                  # the quiet is counted from the start
        rec.add(seq, payload, voiced)
        if speech:
            rec.speech_at = rec.samples
        if a.split_on_silence and (rec.speech_quiet_s() > a.silence_s or rec.samples / RATE >= a.max_s):
            finish(recs.pop(src), min_voiced=15)                      # ≥ 0.3 s of speech
            continue
        if a.split_on_silence:
            began = resident_began(src)
            if began > rec.t0 and began != cut_for.get(src):          # a resident began after this utterance did
                cut_for[src] = began
                print(f"· resident took the turn: {rec.path.name} ends here", flush=True)
                finish(recs.pop(src), min_voiced=15)


if __name__ == "__main__":
    main()
