"""Rollout check on the Mac: one spoken test utterance per side must reach Home Assistant.

    /usr/bin/python3 deploy/smoke.py [--env ~/.aikos/transcriber.env] [--timeout 60]

Speaks a sentence with macOS `say` (no audio file in the repository), sends it as RTP from 127.0.0.1 - a test sender -
first to the door receiver, then to the room receiver, and waits until sensor.talk_transcript_door_test and
sensor.talk_transcript_test show a new transcript. Only *_test entities are written, never live ones
(qualitaet.md §3.8). Needs 127.0.0.1 in AIKOS_TEST_SOURCES. Exit 0 = both sides answered. Called by deploy.sh.
"""
from __future__ import annotations

import argparse
import array
import json
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from launchd import read_env  # noqa: E402

SIDES = (  # side, port, test entity, sentence
    ("door", 5008, "sensor.talk_transcript_door_test", "Guten Tag, dies ist ein automatischer Test der Haustür."),
    ("room", 5006, "sensor.talk_transcript_test", "Hallo, hier spricht der automatische Test im Haus."),
)


def spoken(sentence: str, folder: Path) -> bytes:
    """16 kHz mono PCM, big-endian (RTP L16), of the sentence spoken by macOS."""
    wav = folder / "say.wav"
    for voice in (["-v", "Anna"], []):
        r = subprocess.run(["say", *voice, "-o", str(wav), "--file-format=WAVE", "--data-format=LEI16@16000", sentence],
                           capture_output=True)
        if r.returncode == 0:
            break
    with wave.open(str(wav)) as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise RuntimeError("say did not produce 16 kHz mono 16 bit")
        pcm = array.array("h", w.readframes(w.getnframes()))
    if sys.byteorder == "little":
        pcm.byteswap()
    return pcm.tobytes()


def send(pcm: bytes, port: int) -> None:
    """Paced like a device: 20 ms packets, payload type 96, then one comfort-noise packet (= button released)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    t0 = time.monotonic()
    seq = 0
    for seq, i in enumerate(range(0, len(pcm), 640), start=1):
        s.sendto(struct.pack(">BBHII", 0x80, 96, seq, seq * 320, 0xA1C05) + pcm[i:i + 640], ("127.0.0.1", port))
        time.sleep(max(0.0, t0 + seq * 0.02 - time.monotonic()))
    s.sendto(struct.pack(">BBHII", 0x80, 13, seq + 1, (seq + 1) * 320, 0xA1C05) + b"\x7f", ("127.0.0.1", port))
    s.close()


def state(ha: str, token: str, entity: str) -> tuple:
    req = urllib.request.Request(f"{ha}/api/states/{entity}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            s = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "", ""
        raise
    return s.get("last_updated", ""), s.get("attributes", {}).get("text", "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", type=Path, default=Path("~/.aikos/transcriber.env").expanduser())
    ap.add_argument("--timeout", type=float, default=60.0)
    a = ap.parse_args(argv)
    env = read_env(a.env)
    if "127.0.0.1" not in env.get("AIKOS_TEST_SOURCES", "127.0.0.1").split(","):
        print("smoke: 127.0.0.1 is not a test sender (AIKOS_TEST_SOURCES): refusing to write into live entities")
        return 2
    ha = env["AIKOS_HA_URL"].rstrip("/")
    token = Path(env["AIKOS_HA_TOKEN_FILE"]).read_text().strip()
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for side, port, entity, sentence in SIDES:
            before = state(ha, token, entity)[0]
            t0 = time.time()
            send(spoken(sentence, Path(tmp)), port)
            while time.time() - t0 < a.timeout:
                updated, text = state(ha, token, entity)
                if updated and updated != before:
                    print(f"smoke: {side} ok after {time.time() - t0:.1f} s: “{text}”")
                    break
                time.sleep(0.5)
            else:
                print(f"smoke: {side} FAILED: no new {entity} within {a.timeout:.0f} s")
                ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
