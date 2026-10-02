"""Acceptance test of the aikos call archive (R23) against a running Home Assistant.

Uses only test entities and test events (input_boolean.aikos_test_in_call, event aikos_talk_transcript_test), so the archive
gets three lines marked "test": true. Reading the archive file needs access to the HA config directory; give a command that
prints the file's last lines:

    AIKOS_HA_URL=http://<ha-host>:8123 AIKOS_HA_TOKEN_FILE=<token file> \
    AIKOS_ARCHIVE_TAIL="ssh <host> tail -n 20 <config>/aikos_archive/calls.jsonl" \
    python homeassistant/tests/test_call_archive.py

Exit code 1 if a check fails.
"""
import datetime
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request

URL = os.environ["AIKOS_HA_URL"].rstrip("/") + "/api"
TOKEN = open(os.environ["AIKOS_HA_TOKEN_FILE"], encoding="utf-8").read().strip()
TAIL = shlex.split(os.environ["AIKOS_ARCHIVE_TAIL"])
WAIT = 2.0
failures = 0


def call(path, body=None):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(URL + path, method="POST" if body is not None else "GET", data=raw,
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def check(condition, label):
    global failures
    print(("PASS " if condition else "FAIL ") + label)
    failures += 0 if condition else 1


def archive_lines():
    out = subprocess.run(TAIL, capture_output=True, timeout=60).stdout.decode("utf-8")
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


def main():
    test_call = lambda on: call("/services/input_boolean/turn_" + ("on" if on else "off"), {"entity_id": "input_boolean.aikos_test_in_call"})
    test_call(False)
    time.sleep(WAIT)
    test_call(True)
    time.sleep(WAIT)
    hostile = "Probelauf mit \"Anführungszeichen\", 'Hochkomma'; rm -rf / $(echo x) `id`"
    call("/events/aikos_talk_transcript_test", {
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "side": "door",
        "speaker": "Paketdienst · DHL", "speaker_role": "parcel", "urgent": False, "message": hostile, "text": hostile,
        "language": "de", "device": "", "duration_s": 1.0, "transcribe_s": 0.5, "model": "test"})
    time.sleep(WAIT)
    test_call(False)
    time.sleep(WAIT + 1)
    lines = archive_lines()[-3:]
    types = [l.get("type") for l in lines]
    check(types == ["call_start", "message", "call_end"], f"start, message and end were archived in order ({types})")
    check(all(l.get("test") is True for l in lines), "all three lines are marked test")
    check(len({l.get("call_id") for l in lines}) == 1 and lines[0].get("call_id"), "the three lines share one call_id")
    check(lines and isinstance(lines[0].get("devices"), list) and all({"name", "model", "sw"} <= set(d) for d in lines[0]["devices"]),
          "call_start lists the aikos devices with name, model and firmware version")
    msg = lines[1] if len(lines) > 1 else {}
    check(msg.get("message") == hostile and msg.get("speaker") == "Paketdienst · DHL",
          "visitor text is stored verbatim as data (quotes, shell syntax) and nothing ran")
    check(len(lines) == 3 and isinstance(lines[2].get("duration_s"), (int, float)), "call_end carries the call's duration")
    print("ALL PASS" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
