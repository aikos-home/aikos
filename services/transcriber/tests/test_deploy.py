"""deploy/launchd.py: settings file, takeover from existing agents, and the LaunchAgents it writes."""
import os
import plistlib
import re
import shutil
import subprocess
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
        door = self.plist("door", dict(SHARED, AIKOS_SIDE="door", AIKOS_KNOWN_NAMES="Anna"))
        with self.assertRaises(ValueError):
            launchd.imported(room, door)

    def test_takeover_door_only_split(self):
        """Regression 1.0.1: the door agent has AIKOS_SPLIT=1, the room agent not; that is no disagreement."""
        room = self.plist("room", dict(SHARED, AIKOS_SIDE="room"))
        door = self.plist("door", dict(SHARED, AIKOS_SIDE="door", AIKOS_SPLIT="1"))
        self.assertEqual(launchd.imported(room, door), dict(SHARED, AIKOS_SPLIT="1"))
        self.assertEqual(launchd.imported(door, room), dict(SHARED, AIKOS_SPLIT="1"))


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

    def test_pinned_interpreter(self):
        a = launchd.agent("door", SHARED, Path("/srv/aikos"), Path("/logs"), "/opt/py/bin/python3.12")
        self.assertIn("exec /opt/py/bin/python3.12 -u -m aikos_transcriber >> ", a["ProgramArguments"][2])


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "needs bash (macOS, Linux)")
class DeployScript(unittest.TestCase):
    """Regression 1.0.1: deploy.sh runs with set -eu -o pipefail; lsof exits 1 on mere warnings (a Time Machine SMB mount)."""

    def test_interpreter_from_the_settings_file(self):
        """1.2.3: AIKOS_PYTHON in transcriber.env pins the agents' Python; without it deploy.sh keeps /usr/bin/python3."""
        script = (Path(__file__).resolve().parent.parent / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        fn = re.search(r"^interpreter\(\) \{.*\}$", script, re.M).group(0)
        tmp = Path(tempfile.mkdtemp())
        pinned, plain = tmp / "pinned.env", tmp / "plain.env"
        pinned.write_text("AIKOS_KNOWN_NAMES=Anna\nAIKOS_PYTHON=/opt/uv/python3.12\n")
        plain.write_text("AIKOS_KNOWN_NAMES=Anna\n")
        run = lambda f: subprocess.run(["bash", "-c", f"set -eu -o pipefail; {fn}; interpreter {f}"],
                                       capture_output=True, text=True).stdout.strip()
        self.assertEqual(run(pinned), "/opt/uv/python3.12")
        self.assertEqual(run(plain), "")
        self.assertEqual(run(tmp / "missing.env"), "")

    def test_receiver_count_survives_lsof_warnings(self):
        script = (Path(__file__).resolve().parent.parent / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        fn = re.search(r"^listening\(\) \{.*\}$", script, re.M).group(0)
        bin_dir = Path(tempfile.mkdtemp())
        fake = bin_dir / "lsof"
        fake.write_text("#!/bin/sh\n"
                        "echo 'COMMAND PID NAME'\n"
                        "echo 'Python 1 *:5006'\n"
                        "echo 'Python 2 *:5008'\n"
                        "echo 'lsof: WARNING: can not stat() smbfs file system' >&2\n"
                        "exit 1\n")
        fake.chmod(0o755)
        shell = "\n".join(["set -eu -o pipefail", fn, "n=$(listening)", 'echo "count=$n"'])
        r = subprocess.run(["bash", "-c", shell], capture_output=True, text=True,
                           env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}"))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "count=2"))


if __name__ == "__main__":
    unittest.main()
