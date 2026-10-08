"""Configuration from the environment and the receiver command line built from it (same as transcriber_service.sh)."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from aikos_transcriber.__main__ import receiver_args
from aikos_transcriber.config import Config, ConfigError


class FromEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.token = self.tmp / "token"
        self.token.write_text("t")
        self.base = {"AIKOS_HA_URL": "http://ha.invalid:8123", "AIKOS_HA_TOKEN_FILE": str(self.token)}

    def test_defaults_per_side(self):
        room = Config.from_env(dict(self.base, AIKOS_SIDE="room"))
        door = Config.from_env(dict(self.base, AIKOS_SIDE="door"))
        self.assertEqual((room.port, room.live, room.split), (5006, False, False))
        self.assertEqual((door.port, door.live, door.live_entity), (5008, True, "sensor.talk_live_door"))
        self.assertEqual(room.test_sources, "127.0.0.1")              # unset → 127.0.0.1
        self.assertEqual(room.activity_file, room.state_dir / "room_active")

    def test_empty_test_sources_means_none(self):
        c = Config.from_env(dict(self.base, AIKOS_SIDE="room", AIKOS_TEST_SOURCES=""))
        self.assertEqual(c.test_sources, "")

    def test_empty_values_fall_back_to_defaults(self):
        c = Config.from_env(dict(self.base, AIKOS_SIDE="door", AIKOS_PORT="", AIKOS_LIVE="", AIKOS_WHISPER_URL=""))
        self.assertEqual((c.port, c.live), (5008, True))
        self.assertTrue(c.whisper_url.endswith("/v1/audio/transcriptions"))

    def test_errors(self):
        for env in ({}, dict(self.base), dict(self.base, AIKOS_SIDE="hall"),
                    dict(self.base, AIKOS_SIDE="room", AIKOS_HA_TOKEN_FILE=str(self.tmp / "missing"))):
            with self.subTest(env=env), self.assertRaises(ConfigError):
                Config.from_env(env)


class ReceiverArgs(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "token").write_text("t")
        self.base = {"AIKOS_HA_URL": "http://ha.invalid:8123", "AIKOS_HA_TOKEN_FILE": str(tmp / "token"),
                     "AIKOS_STATE_DIR": str(tmp / "state"), "AIKOS_RECORDINGS": str(tmp / "rec"), "AIKOS_KNOWN_NAMES": "Anna,Jonas"}

    def args(self, **env):
        a = receiver_args(Config.from_env(dict(self.base, **env)), "/usr/bin/python3")
        return a, dict(zip(a[::1], a[1::1]))

    def test_room_side(self):
        a, kv = self.args(AIKOS_SIDE="room")
        self.assertEqual(kv["--port"], "5006")
        self.assertIn("--activity-file", a)
        self.assertNotIn("--live", a)
        self.assertIn("-m aikos_transcriber.worker {wav} --side room --source-ip {src}", kv["--exec"])
        self.assertIn("--delete-wav", kv["--exec"])
        self.assertNotIn("--activity-file", kv["--exec"])              # only the door side filters echoes

    def test_door_side(self):
        a, kv = self.args(AIKOS_SIDE="door", AIKOS_SPLIT="1")
        self.assertEqual(kv["--live"], "sensor.talk_live_door")
        self.assertIn("--split-on-silence", a)
        self.assertTrue(kv["--live-quiet-file"].endswith("room_active"))
        self.assertIn("--activity-file", kv["--exec"])
        self.assertIn('"keep_alive":-1', kv["--on-start"])

    def test_visitor_translation_room_only_and_off_by_default(self):
        _, off = self.args(AIKOS_SIDE="room")
        _, on = self.args(AIKOS_SIDE="room", AIKOS_VISITOR_TRANSLATION="1")
        _, door = self.args(AIKOS_SIDE="door", AIKOS_VISITOR_TRANSLATION="1")
        self.assertNotIn("--translate-to-visitor", off["--exec"])          # R28 off: the worker call is exactly as before
        self.assertTrue(on["--exec"].endswith("--translate-to-visitor"))
        self.assertNotIn("--translate-to-visitor", door["--exec"])         # the door side never translates for the visitor

    def test_mic_check_off_by_default_both_sides(self):
        _, off = self.args(AIKOS_SIDE="room")
        _, room = self.args(AIKOS_SIDE="room", AIKOS_MIC_CHECK="1")
        _, door = self.args(AIKOS_SIDE="door", AIKOS_MIC_CHECK="1")
        self.assertNotIn("--mic-check", off["--exec"])
        self.assertIn("--mic-check", room["--exec"])
        self.assertIn("--mic-check", door["--exec"])


if __name__ == "__main__":
    unittest.main()
