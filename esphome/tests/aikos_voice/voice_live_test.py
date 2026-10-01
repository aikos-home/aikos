"""Live regression test of a door talk computer running aikos_voice v2 (role door), run before every aikos_voice tag.

This PC plays a room key: it sends RTP to the door and reports its key state through Home Assistant (the door's test
action `key_state`, standing in for the key's own packet_transport message), and checks the rules of voice v2 that a
door shows on the network. Needs: Home Assistant with the door's ESPHome device, the door on the network, nothing else
talking to it during the ~2 min run. The test sets the door's "Key addresses" and "Transcriber address" to this PC and
puts both back at the end.

Configuration from the environment (nothing house-specific in this file):
  AIKOS_HA_URL          Home Assistant base URL, e.g. http://homeassistant.local:8123
  AIKOS_HA_TOKEN_FILE   file holding a long-lived access token
  AIKOS_DOOR_HOST       the door talk computer's IP address
  AIKOS_TEST_IP         this PC's IP address as the door sees it
  AIKOS_DOOR_NODE       the door's ESPHome node name with "_" (default aikos_intercom_talk)

  python voice_live_test.py
The door config must count the call triggers in template sensors "Calls started" / "Calls ended" (on_call_start /
on_call_end) and offer the API actions ring, visitor_speak, key_state(host, state) and call_end (see the README).
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
ME = "%s:%d" % (ME_IP, KEY_PORT)


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


def on(eid):
    return state(eid) == "on"


def service(name, data=None):
    ha("/api/services/esphome/%s_%s" % (E, name), data or {})


def set_text(name, value):
    ha("/api/services/text/set_value", {"entity_id": "text.%s_%s" % (E, name), "value": value})


def counters():
    time.sleep(5.6)  # the device publishes its packet counters every 5 s
    return {k: num("sensor.%s_rtp_packets_%s" % (E, k)) for k in ("sent", "received", "held_back")}


def calls():
    return {k: num("sensor.%s_calls_%s" % (E, k)) for k in ("started", "ended")}


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


class Key:
    """This PC's key state, refreshed every second like a real key's packets (0 idle, 1 in the call, 2 holding)."""

    def __init__(self):
        self.value = None  # None = the key is gone: no messages at all
        self.run = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.run:
            if self.value is not None:
                try:
                    service("key_state", {"host": ME, "state": self.value})
                except Exception as e:  # one lost message is what the refresh is for
                    print("  (key_state failed: %s)" % e)
            time.sleep(1.0)

    def set(self, v):
        self.value = v
        if v is not None:
            service("key_state", {"host": ME, "state": v})


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


def voice(packets):  # L16 frames (latch frames included; there are at most three per new target)
    return [d for _, d in packets if len(d) > 12 and (d[1] & 0x7F) == 96]


def cn(packets):
    return [d for _, d in packets if (d[1] & 0x7F) == 13]


def main():
    ear = Ear(KEY_PORT)
    tap = Ear(TAP_PORT)
    ear.open_firewall(DOOR)
    tap.open_firewall(DOOR)
    key = Key()
    old_keys = state("text.%s_key_addresses" % E)
    old_tap = state("text.%s_transcriber_address" % E)
    try:
        print("0) clean start: no call, this PC is the only key and the transcriber")
        service("call_end")
        set_text("key_addresses", "pc-test=%s" % ME)
        set_text("transcriber_address", "%s:%d" % (ME_IP, TAP_PORT))
        time.sleep(2.0)
        c0, k0 = counters(), calls()
        ear.take(), tap.take()

        print("1) no call: the door mic is closed, a key that doesn't hold is never played")
        send_frames(ear.s, 30)
        time.sleep(1.0)
        c1 = counters()
        check(not on("binary_sensor.%s_in_call" % E), "no call")
        check(len(voice(ear.take())) <= 3 and not voice(tap.take()), "door mic closed: no audio to key or transcriber")
        check(c1["received"] == c0["received"] and c1["held_back"] > c0["held_back"], "not played, held back")

        print("2) case 2: the key holds without a ring -> a call; the door plays it; the door mic opens")
        key.set(2)
        time.sleep(1.0)
        check(on("binary_sensor.%s_in_call" % E), "the call is on")
        check(calls()["started"] == k0["started"] + 1, "on_call_start fired once")
        check(on("binary_sensor.%s_room_key_holds" % E), "the key has the floor")
        ear.take(), tap.take()
        send_frames(ear.s, 50)
        c2 = counters()
        check(c2["received"] >= c1["received"] + 45, "its audio played (%d frames)" % (c2["received"] - c1["received"]))
        tl = voice(tap.take())
        check(len(tl) > 100, "the door mic is open: the transcriber gets the door's audio (%d frames)" % len(tl))

        print("3) the key releases but stays in the call: not played; the door's audio reaches it")
        key.set(1)
        time.sleep(1.0)
        check(not on("binary_sensor.%s_room_key_holds" % E), "nobody has the floor")
        ear.take()
        send_frames(ear.s, 40)
        time.sleep(1.0)
        c3 = counters()
        check(c3["received"] == c2["received"], "a key that doesn't hold is not played (the lock)")
        kl = voice(ear.take())
        check(len(kl) > 60, "the door mic reaches the key (%d frames in ~2 s)" % len(kl))
        seqs = [struct.unpack(">H", d[2:4])[0] for d in kl]
        check(all(((b - a) & 0xFFFF) == 1 for a, b in zip(seqs, seqs[1:])), "sequence numbers without gaps")

        print("4) mute: while the door speaker plays the key, the door mic does not reach the key (echo)")
        key.set(2)
        time.sleep(1.0)
        stop = threading.Event()

        def talk():
            while not stop.is_set():
                send_frames(ear.s, 10)

        t = threading.Thread(target=talk, daemon=True)
        t.start()
        time.sleep(0.5)
        ear.take()
        time.sleep(1.5)
        during = voice(ear.take())
        stop.set()
        t.join()
        check(len(during) <= 5, "muted towards the key while it is played (%d frames in 1.5 s)" % len(during))
        time.sleep(0.6)
        ear.take()
        time.sleep(1.0)
        after = voice(ear.take())
        check(len(after) > 30, "open again once the speaker is quiet (%d frames in 1 s)" % len(after))

        print("5) the key's messages stop: its hold ends after 3 s")
        key.set(None)
        time.sleep(4.5)
        check(not on("binary_sensor.%s_room_key_holds" % E), "hold released without a release message")

        print("6) silence: 10 s without speech ends the call; the end packet reaches the key")
        ear.take()
        t6 = time.time()  # room noise that sounds like speech restarts the 10 s, so wait up to a minute
        while on("binary_sensor.%s_in_call" % E) and time.time() - t6 < 60:
            time.sleep(1.0)
        waited = time.time() - t6
        check(not on("binary_sensor.%s_in_call" % E), "the call is over (%.0f s after the key went quiet)" % (waited + 4.5))
        check(waited + 4.5 >= 9.5, "not before 10 s of silence")
        check(calls()["ended"] == k0["ended"] + 1, "on_call_end fired once")
        check(len(cn(ear.take())) >= 1, "an end packet (PT 13) at the key")

        print("7) case 1: ring, the visitor presses Sprechen -> a call nobody answered; a key joins -> answered")
        service("ring")
        service("visitor_speak")
        time.sleep(1.0)
        check(on("binary_sensor.%s_in_call" % E) and not on("binary_sensor.%s_answered" % E), "call on, not answered")
        key.set(1)
        time.sleep(1.5)
        check(on("binary_sensor.%s_answered" % E), "a key joined (short press): answered")
        check(calls()["started"] == k0["started"] + 2, "the second call")
        key.set(0)
        service("call_end")
        time.sleep(1.0)
        check(not on("binary_sensor.%s_in_call" % E), "ended from outside")
    finally:
        key.run = False
        set_text("key_addresses", old_keys if old_keys not in ("unknown", "unavailable") else "")
        set_text("transcriber_address", old_tap if old_tap not in ("unknown", "unavailable") else "")
        ear.run = tap.run = False
    failed = [w for ok, w in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
