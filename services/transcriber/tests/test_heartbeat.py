"""heartbeat: busy is not dead, a stalled connection gets one more try, the Mac's 49.7-day TCP wrap is named as such,
and the push carries status + message but the token never reaches the output (21.10.2026: 41 false "whisper down")."""
import io
import socket
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import _path  # noqa: F401
from aikos_transcriber import heartbeat as hb

DAY = 86400.0
NOW = 1_800_000_000.0


class Fake(BaseHTTPRequestHandler):
    """Whisper (/health, its inference path held by a long request), Home Assistant (/api/) and a push monitor (/push/)."""
    health = 200
    pushes: list = []
    inference = threading.Event()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(self.health)
        elif self.path == "/api/":
            self.send_response(200 if self.headers.get("Authorization") == "Bearer ha-token" else 401)
        elif self.path.startswith("/push/"):
            Fake.pushes.append(self.path)
            self.send_response(200)
        else:
            self.send_response(404)
        self.end_headers()

    def do_POST(self):                                                    # a transcription that takes a while
        Fake.inference.set()
        time.sleep(1.5)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class Heartbeat(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        Fake.health, Fake.pushes = 200, []
        base = f"http://127.0.0.1:{self.srv.server_port}"
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ha.token").write_text("ha-token\n")
        (tmp / "push.token").write_text("s3cret-push\n")
        self.base, self.tmp = base, tmp
        self.env = {"AIKOS_HA_URL": base, "AIKOS_HA_TOKEN_FILE": str(tmp / "ha.token"),
                    "AIKOS_WHISPER_URL": base + "/v1/audio/transcriptions",
                    "AIKOS_HEARTBEAT_URL": base + "/push", "AIKOS_HEARTBEAT_TOKEN_FILE": str(tmp / "push.token")}

    def check(self, uptime_d=10.0, waits=120, receivers=2, http=hb.get):
        return hb.check(self.env, http=http, receivers=lambda: receivers, booted=lambda: NOW - uptime_d * DAY,
                        waits=lambda: waits, now=NOW)

    def test_all_well_is_up(self):
        self.assertEqual(self.check()[:2], ("up", "ok"))

    def test_busy_whisper_is_up(self):
        """/health is answered while a transcription runs (whisper-server keeps it outside the inference lock)."""
        Fake.inference.clear()
        req = urllib.request.Request(self.base + "/v1/audio/transcriptions", data=b"audio", method="POST")
        t = threading.Thread(target=lambda: urllib.request.urlopen(req, timeout=5).read())
        t.start()
        self.assertTrue(Fake.inference.wait(2))
        t0 = time.time()
        self.assertEqual(self.check()[:2], ("up", "ok"))
        self.assertLess(time.time() - t0, 1.0)
        t.join()

    def test_a_stalled_connection_gets_one_more_try(self):
        """The first connect hangs (a local port the server still holds in TIME_WAIT), the second one answers: up."""
        calls = []

        def http(url, headers=None):
            calls.append(url)
            if len(calls) == 1:
                raise hb.Missed("stalled")
            return hb.get(url, headers)
        status, msg, notes = self.check(http=http)
        self.assertEqual((status, msg), ("up", "ok"))
        self.assertEqual(calls[:2], [self.base + "/health"] * 2)
        self.assertIn("whisper: the first connection stalled", notes[0])

    def test_two_stalls_are_down(self):
        def http(url, headers=None):
            if url.endswith("/health"):
                raise hb.Missed("stalled")
            return hb.get(url, headers)
        self.assertEqual(self.check(http=http)[:2], ("down", "whisper not answering (stalled, 2 tries)"))

    def test_refused_is_down_at_once(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                                         # nothing listens there
        self.env["AIKOS_WHISPER_URL"] = f"http://127.0.0.1:{port}/v1/audio/transcriptions"
        self.assertEqual(self.check()[:2], ("down", "whisper down (refused)"))

    def test_loading_model_is_down(self):
        Fake.health = 503
        self.assertEqual(self.check()[:2], ("down", "whisper loading model"))

    def test_receivers_and_ha(self):
        (self.tmp / "ha.token").write_text("wrong")
        self.assertEqual(self.check(receivers=1)[:2], ("down", "receivers 1/2; HA 401"))
        self.env["AIKOS_HA_TOKEN_FILE"] = str(self.tmp / "missing")
        self.assertIn("HA token file not readable", self.check()[1])

    def test_mac_past_the_tcp_wrap_needs_a_restart(self):
        """21.10.2026: up 51.7 d, 13,272 TIME_WAIT. Whisper itself is fine, the message says what to do."""
        status, msg, _ = self.check(uptime_d=51.7, waits=13272)
        self.assertEqual(status, "down")
        self.assertTrue(msg.startswith("Mac restart needed: up 51.7 d"), msg)
        self.assertIn("(13272 now)", msg)
        self.assertNotIn("whisper", msg)

    def test_past_the_wrap_but_time_wait_ends_is_up(self):
        """A macOS without the bug: a long uptime alone is no fault."""
        self.assertEqual(self.check(uptime_d=60, waits=150)[0], "up")

    def test_ports_running_out_whatever_the_uptime(self):
        status, msg, _ = self.check(uptime_d=3, waits=9000)
        self.assertEqual((status, msg), ("down", "TCP ports running out: 9000 TIME_WAIT"))

    def test_restart_due_is_named_from_45_days(self):
        status, msg, _ = self.check(uptime_d=46)
        self.assertEqual(status, "up")
        self.assertRegex(msg, r"^ok; restart the Mac before \d{4}-\d\d-\d\d \d\d:\d\d")
        self.assertEqual(self.check(uptime_d=44)[1], "ok")

    def test_not_a_mac(self):
        status, msg, _ = hb.check(self.env, receivers=lambda: 2, booted=lambda: None, waits=lambda: 99999, now=NOW)
        self.assertEqual((status, msg), ("up", "ok"))

    def test_push_carries_status_and_message_never_the_token(self):
        out = io.StringIO()
        with mock.patch.dict("os.environ", self.env, clear=True), \
                mock.patch.object(hb, "listening", return_value=1), mock.patch.object(hb, "boot_time", return_value=None), \
                redirect_stdout(out):
            self.assertEqual(hb.main([]), 0)
        self.assertEqual(len(Fake.pushes), 1)
        path, _, query = Fake.pushes[0].partition("?")
        self.assertEqual(path, "/push/s3cret-push")
        self.assertEqual(urllib.parse.parse_qs(query, keep_blank_values=True),
                         {"status": ["down"], "msg": ["receivers 1/2"], "ping": [""]})
        self.assertIn("down: receivers 1/2", out.getvalue())
        self.assertNotIn("s3cret", out.getvalue())

    def test_failed_push_names_no_url(self):
        self.env["AIKOS_HEARTBEAT_URL"] = self.base + "/nowhere"
        out = io.StringIO()
        with mock.patch.dict("os.environ", self.env, clear=True), mock.patch.object(hb, "listening", return_value=2), \
                mock.patch.object(hb, "boot_time", return_value=None), mock.patch.object(hb.time, "sleep"), \
                redirect_stdout(out):
            self.assertEqual(hb.main([]), 1)
        self.assertIn("push failed: HTTPError 404", out.getvalue())
        self.assertNotIn("s3cret", out.getvalue())

    def test_dry_run_from_the_settings_file(self):
        f = self.tmp / "transcriber.env"
        f.write_text("# house settings\n" + "".join(f"{k}={v}\n" for k, v in self.env.items()))
        out = io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(hb, "listening", return_value=2), \
                mock.patch.object(hb, "boot_time", return_value=None), redirect_stdout(out):
            self.assertEqual(hb.main(["--dry-run", "--env", str(f)]), 0)
        self.assertEqual(out.getvalue().strip(), "up: ok")
        self.assertEqual(Fake.pushes, [])

    def test_missing_settings(self):
        with mock.patch.dict("os.environ", {}, clear=True), redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(hb.main([]), 2)


class Host(unittest.TestCase):
    def test_lsof_warnings_do_not_count(self):
        """lsof exits 1 on mere warnings (an SMB mount); a port counts when lsof lists a socket for it."""
        outs = {"-iUDP:5006": "COMMAND PID NAME\nPython 1 *:5006\n", "-iUDP:5008": ""}
        with mock.patch.object(hb, "_run", side_effect=lambda cmd: outs[cmd[-1]]):
            self.assertEqual(hb.listening(), 1)

    def test_boot_time_from_sysctl(self):
        with mock.patch.object(hb.sys, "platform", "darwin"), mock.patch.object(
                hb, "_run", return_value="{ sec = 1788102892, usec = 373046 } Sun Aug 30 17:14:52 2026\n"):
            self.assertEqual(hb.boot_time(), 1788102892.0)
        with mock.patch.object(hb.sys, "platform", "linux"):
            self.assertIsNone(hb.boot_time())

    def test_time_waits_from_netstat(self):
        out = ("Active Internet connections (including servers)\n"
               "tcp4  0  0  127.0.0.1.60521  127.0.0.1.6667  TIME_WAIT\n"
               "tcp4  0  0  127.0.0.1.6667   127.0.0.1.60521 TIME_WAIT  \n"
               "tcp4  0  0  *.6667           *.*             LISTEN\n")
        with mock.patch.object(hb, "_run", return_value=out):
            self.assertEqual(hb.time_waits(), 2)

    def test_the_wrap_is_49_7_days(self):
        self.assertAlmostEqual(hb.TCP_WRAP_S / DAY, 49.71, places=2)


if __name__ == "__main__":
    unittest.main()
