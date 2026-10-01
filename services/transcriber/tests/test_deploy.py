"""deploy/launchd.py: settings file, takeover from existing agents, and the LaunchAgents it writes."""
import os
import plistlib
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy"))
import launchd  # noqa: E402

SHARED = {"AIKOS_HA_URL": "http://ha.invalid:8123", "AIKOS_HA_TOKEN_FILE": "/token", "AIKOS_KNOWN_NAMES": "Anna,Jonas",
          "AIKOS_TEST_SOURCES": ""}


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_read_env(self):
        f = self.tmp / "env"
        f.write_text("# comment\n\nAIKOS_HA_URL=http://ha.invalid:8123\nAIKOS_TEST_SOURCES=\n AIKOS_KNOWN_NAMES = Anna,Jonas \n")
        self.assertEqual(launchd.read_env(f), {"AIKOS_HA_URL": "http://ha.invalid:8123", "AIKOS_TEST_SOURCES": "",
                                               "AIKOS_KNOWN_NAMES": "Anna,Jonas"})

    def test_read_env_refuses_foreign_and_per_side_keys(self):
        for line in ("PATH=/bin", "AIKOS_SIDE=door", "AIKOS_PORT=5008", "no equals sign"):
            f = self.tmp / "env"
            f.write_text(line + "\n")
            with self.subTest(line=line), self.assertRaises(ValueError):
                launchd.read_env(f)

    def plist(self, name, env):
        p = self.tmp / name
        p.write_bytes(plistlib.dumps({"Label": name, "EnvironmentVariables": env}))
        return p

    def test_takeover_from_existing_agents(self):
        room = self.plist("room", dict(SHARED, AIKOS_SIDE="room", PATH="/usr/bin"))
        door = self.plist("door", dict(SHARED, AIKOS_SIDE="door", PATH="/usr/bin"))
        self.assertEqual(launchd.imported(room, door), SHARED)
        env = self.tmp / "settings" / "transcriber.env"
        launchd.write_env(env, launchd.imported(room, door))
        self.assertEqual(launchd.read_env(env), SHARED)
        if os.name == "posix":
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):                      # existing settings are never overwritten
            launchd.write_env(env, {})

    def test_takeover_refuses_disagreeing_agents(self):
        room = self.plist("room", dict(SHARED, AIKOS_SIDE="room"))
        door = self.plist("door", dict(SHARED, AIKOS_SIDE="door", AIKOS_SPLIT="1"))
        with self.assertRaises(ValueError):
            launchd.imported(room, door)


class Agents(unittest.TestCase):
    def test_agent_per_side(self):
        for side in ("room", "door"):
            a = launchd.agent(side, SHARED, Path("/srv/aikos"), Path("/logs"))
            plistlib.loads(plistlib.dumps(a))                            # a valid plist
            self.assertEqual(a["Label"], f"home.aikos.transcriber.{side}")
            self.assertEqual(a["EnvironmentVariables"], dict(SHARED, AIKOS_SIDE=side, PATH=launchd.PATH))
            self.assertEqual(Path(a["WorkingDirectory"]), Path("/srv/aikos/services/transcriber"))
            self.assertEqual(a["ProgramArguments"][:2], ["/bin/bash", "-c"])
            self.assertIn("/usr/bin/python3 -u -m aikos_transcriber >> ", a["ProgramArguments"][2])
            self.assertIn(f"transcriber-{side}.log", a["ProgramArguments"][2])
            self.assertTrue(a["KeepAlive"] and a["RunAtLoad"])
        with self.assertRaises(ValueError):
            launchd.agent("hall", SHARED, Path("/srv/aikos"), Path("/logs"))


if __name__ == "__main__":
    unittest.main()
