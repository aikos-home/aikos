"""Live regression test of a door talk computer running aikos_voice (role door), run before every aikos_voice tag.

This PC plays a room key: it talks RTP to the door, asks Home Assistant to forward "key holds/released" (the door's
actions `peer_talk` and `call_end`), and checks every rule tested live on 2026-10-01. Needs: Home Assistant with the
door's ESPHome device, the door on the network, nothing else talking to it during the ~1 min run.

Configuration from the environment (nothing house-specific in this file):
  AIKOS_HA_URL          Home Assistant base URL, e.g. http://homeassistant.local:8123
  AIKOS_HA_TOKEN_FILE   file holding a long-lived access token
  AIKOS_DOOR_HOST       the door talk computer's IP address
  AIKOS_TEST_IP         this PC's IP address as the door sees it
  AIKOS_DOOR_NODE       the door's ESPHome node name with "_" (default aikos_intercom_talk)

  python voice_live_test.py
Exit code 0 = all checks passed. Windows drops unsolicited UDP, so the test sends first on every port it listens on.
"""
import json
import os
import socket
import struct
import sys
import threading
import time
import urllib.request


def need(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit("set %s (see the docstring)" % name)
    return v


HA = need("AIKOS_HA_URL").rstrip("/")
TOK = open(need("AIKOS_HA_TOKEN_FILE"), encoding="utf-8").read().strip()
DOOR = (need("AIKOS_DOOR_HOST"), 5004)
ME_IP = need("AIKOS_TEST_IP")
KEY_PORT, TAP_PORT = 5104, 5105     # not 5004: a real key may run on the test PC
E = os.environ.get("AIKOS_DOOR_NODE", "aikos_intercom_talk")

def ha(path, body=None, method="POST"):
    r = urllib.request.Request(HA + path, method=method, data=None if body is None else json.dumps(body).encode(),
                               headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=15) as x:
        return json.loads(x.read() or b"null")

def state(eid):
    return ha("/api/states/" + eid, method="GET")["state"]

def num(eid):
    v = state(eid)
    return float(v) if v not in ("unknown", "unavailable") else 0.0

def service(name, data):
    ha("/api/services/esphome/%s_%s" % (E, name), data)

def counters():
    time.sleep(5.6)  # the device publishes its counters every 5 s
    return {k: num("sensor.%s_rtp_packets_%s" % (E, k)) for k in ("sent", "received", "held_back")}

results = []
def check(cond, what):
    results.append((bool(cond), what))
    print(("  ok   " if cond else "  FAIL ") + what, flush=True)

class Ear:
    """Collects what the door sends to one local port."""
    def __init__(self, port):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("0.0.0.0", port))
        self.s.settimeout(0.1)
        self.got = []
        self.run = True
        threading.Thread(target=self._rx, daemon=True).start()
    def _rx(self):
        while self.run:
            try:
                d, src = self.s.recvfrom(2000)
            except socket.timeout:
                continue
            if src[0] == DOOR[0]:
                self.got.append((time.time(), d))
    def take(self):
        g, self.got = self.got, []
        return g
    def open_firewall(self, to):  # Windows drops unsolicited UDP until this socket has sent to the sender
        self.s.sendto(bytes([0x80, 0x60]) + bytes(10), to)

def frames(n, value=3000, seq0=1000):
    out = []
    for k in range(n):
        p = struct.pack(">BBHII", 0x80, 96, (seq0 + k) & 0xFFFF, (k * 320) & 0xFFFFFFFF, 0x4B455931)
        out.append(p + struct.pack(">320h", *([value] * 320)))
    return out

def send_frames(sock, n, value=3000):
    for p in frames(n, value):
        sock.sendto(p, DOOR)
        time.sleep(0.02)

def kinds(packets):
    l16 = [d for _, d in packets if len(d) > 12 and (d[1] & 0x7F) == 96]
    cn = [d for _, d in packets if (d[1] & 0x7F) == 13]
    ka = [d for _, d in packets if len(d) == 12]
    return l16, cn, ka

def main():
    key = Ear(KEY_PORT)
    tap = Ear(TAP_PORT)
    key.open_firewall(DOOR)
    tap.open_firewall(DOOR)
    me = "%s:%d" % (ME_IP, KEY_PORT)
    old_tap = state("text.%s_transcriber_address" % E)
    try:
        print("0) clean start")
        service("call_end", {})
        ha("/api/services/switch/turn_off", {"entity_id": "switch.%s_talk_test" % E})
        ha("/api/services/text/set_value", {"entity_id": "text.%s_transcriber_address" % E,
                                            "value": "%s:%d" % (ME_IP, TAP_PORT)})
        c0 = counters()
        key.take(), tap.take()

        print("1) lock: a key that does not hold is never played")
        send_frames(key.s, 40)  # more than the 25-frame pre-buffer: the oldest fall out and are counted
        c1 = counters()
        check(c1["received"] == c0["received"], "nothing played without a hold")
        check(c1["held_back"] >= c0["held_back"] + 1, "held back counted (%d -> %d)" % (c0["held_back"], c1["held_back"]))

        print("2) the key holds: conversation on, latch frames, its audio played")
        service("peer_talk", {"held": True, "peer_host": me})
        time.sleep(1.0)
        l16, cn, ka = kinds(key.take())
        check(state("binary_sensor.%s_in_call" % E) == "on", "conversation on")
        silent = [d for d in l16 if len(d) == 652 and not any(d[12:])]
        check(len(silent) >= 1, "silent latch frame(s) at the key (%d)" % len(silent))
        send_frames(key.s, 50)
        c2 = counters()
        check(c2["received"] >= c1["received"] + 45, "its audio played (%d frames)" % (c2["received"] - c1["received"]))

        print("3) the key releases: silent again")
        service("peer_talk", {"held": False, "peer_host": ""})
        time.sleep(0.5)
        send_frames(key.s, 40)
        c3 = counters()
        check(c3["received"] == c2["received"], "not played after the release")
        check(c3["held_back"] > c2["held_back"], "held back again")

        print("4) the visitor talks: frames to the key and the transcriber, end packet on release")
        key.take(), tap.take()
        ha("/api/services/switch/turn_on", {"entity_id": "switch.%s_talk_test" % E})
        time.sleep(0.3)
        send_frames(key.s, 25)  # half-duplex: the key's audio must not play now
        time.sleep(1.5)
        ha("/api/services/switch/turn_off", {"entity_id": "switch.%s_talk_test" % E})
        time.sleep(1.0)
        kl16, kcn, _ = kinds(key.take())
        tl16, tcn, _ = kinds(tap.take())
        check(len(kl16) >= 80, "visitor frames at the key (%d in ~2.5 s)" % len(kl16))
        check(kl16 and (kl16[0][1] & 0x80), "marker bit on the first frame of the spurt")
        check(len(kcn) == 1 and len(kcn[0]) == 13, "one end packet (PT 13) at the key")
        check(len(tl16) >= 80 and len(tcn) == 1, "the same to the transcriber (%d + %d)" % (len(tl16), len(tcn)))
        seqs = [struct.unpack(">H", d[2:4])[0] for d in kl16]
        check(all(((b - a) & 0xFFFF) == 1 for a, b in zip(seqs, seqs[1:])), "sequence numbers without gaps")
        c4 = counters()
        check(c4["received"] == c3["received"], "half-duplex: nothing played while the visitor talked")

        print("5) the end")
        service("call_end", {})
        time.sleep(1.0)
        check(state("binary_sensor.%s_in_call" % E) == "off", "conversation off")
    finally:
        ha("/api/services/text/set_value", {"entity_id": "text.%s_transcriber_address" % E, "value": old_tap})
        key.run = tap.run = False
    failed = [w for ok, w in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 0 if not failed else 1

if __name__ == "__main__":
    sys.exit(main())
