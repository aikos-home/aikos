"""Test helpers: synthetic recordings and RTP packets, and fake Whisper / LLM / Home Assistant servers on localhost."""
import array
import json
import math
import struct
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RATE = 16000


def tone(seconds: float, amp: int = 3000, hz: int = 300) -> array.array:
    return array.array("h", [int(amp * math.sin(2 * math.pi * hz * i / RATE)) for i in range(int(seconds * RATE))])


def silence(seconds: float) -> array.array:
    return array.array("h", [0] * int(seconds * RATE))


def write_wav(path: Path, *parts: array.array) -> Path:
    x = array.array("h")
    for p in parts:
        x.extend(p)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(x.tobytes())
    return path


def rtp(seq: int, samples: array.array, pt: int = 96) -> bytes:
    """One RTP packet: version 2, payload type pt, big-endian L16 payload."""
    payload = struct.pack(f">{len(samples)}h", *samples)
    return struct.pack(">BBHII", 0x80, pt, seq & 0xFFFF, seq * 320, 0x12345678) + payload


class FakeServers:
    """Whisper (/whisper), Ollama (/api/chat) and Home Assistant (/api/...) in one local HTTP server.
    heard: recording-name prefix → (German text, verbose result); every HA POST is recorded in .calls."""

    def __init__(self, heard: dict, translation: str = "", visitor_language: str = ""):
        self.heard, self.translation, self.calls = heard, translation, []
        self.visitor_language, self.gets, self.chats = visitor_language, [], []   # R28: the call log's language; what was asked
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, obj):
                raw = json.dumps(obj).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

            def do_GET(self):
                outer.gets.append(self.path)
                if self.path.startswith("/api/states/sensor.aikos_call_log"):
                    self.send({"state": "x", "attributes": {"visitor_language": outer.visitor_language}})
                elif self.path == "/api/states":
                    self.send([{"entity_id": "sensor.aikos_roomkey_test_ip_address", "state": "192.0.2.44",
                                "attributes": {"friendly_name": "aikos RoomKey Test IP address"}}])
                else:
                    self.send({"state": "2000-01-01T00:00:00+00:00", "attributes": {"text": ""}})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path.startswith("/whisper"):
                    name = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
                    key = next(k for k in outer.heard if name.startswith(k))
                    text, verbose = outer.heard[key]
                    self.send(verbose if b"verbose_json" in body else {"text": text})
                elif self.path == "/api/chat":
                    outer.chats.append(json.loads(body))
                    if json.loads(body).get("format") == "json":
                        self.send({"message": {"content": json.dumps({"speaker": "", "kind": "none", "role": ""})}})
                    else:
                        self.send({"message": {"content": outer.translation}})
                else:
                    outer.calls.append((self.path, json.loads(body) if body else None))
                    self.send({})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
