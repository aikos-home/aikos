"""deploy/deploy.sh: the whole roll-out on a stand-in Mac (git, launchctl and curl replaced), including the way back."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy" / "deploy.sh"
pytestmark = pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="needs bash (macOS, Linux)")

GIT = r"""#!/bin/sh
# git -C <repo> <command> ...: tags are folders in $FAKE_TREE
shift 2
for a; do last=$a; done
case "$1" in
  fetch) exit 0 ;;
  rev-parse) tag=${last%^\{commit\}}; [ -d "$FAKE_TREE/$tag" ] || exit 1; echo abc1234 ;;
  archive) [ -d "$FAKE_TREE/$3" ] || exit 1; tar -C "$FAKE_TREE/$3" -cf - services/tts ;;
  *) exit 2 ;;
esac
"""
LAUNCHCTL = """#!/bin/sh
echo "launchctl $*" >> "$FAKE_LOG"
"""
# the running release is the one the LaunchAgent names; its VERSION file is what its health says
CURL = r"""#!/bin/sh
rel=$(sed -n 's/^RELEASE=//p' "$HOME/Library/LaunchAgents/home.aikos.tts.plist" 2>/dev/null)
[ -n "$rel" ] && [ ! -f "$rel/HEALTH_DOWN" ] || exit 7
case "$*" in
  *selftest*) if [ -f "$rel/SELFTEST_FAIL" ]; then echo '{"ok": false, "whisper_ok": false}'; else echo '{"ok": true, "seconds": 1.9, "whisper_ok": true}'; fi ;;
  *health*) echo "{\"ok\": true, \"version\": \"$(cat "$rel/VERSION")\", \"engine\": \"fake\"}" ;;
  *) exit 22 ;;
esac
"""
INSTALL = """#!/bin/sh
if [ "$1" = --build-only ]; then
  [ ! -f "$2/BUILD_FAIL" ] || exit 1
  mkdir -p "$2/.venv-fake/bin"
  printf '#!/bin/sh\\nexec "%s" "$@"\\n' "$FAKE_PYTHON" > "$2/.venv-fake/bin/python"
  chmod +x "$2/.venv-fake/bin/python"
  echo "built"
  echo "$2/.venv-fake/bin/python"
  exit 0
fi
[ ! -f "$1/INSTALL_FAIL" ] || exit 1
echo "RELEASE=$1" > "$HOME/Library/LaunchAgents/home.aikos.tts.plist"
"""


class Mac:
    """A home folder with a clone, the replaced tools and releases to tag."""

    def __init__(self, tmp: Path):
        self.home = tmp / "home"
        self.tree = tmp / "tree"
        self.bin = tmp / "bin"
        self.log = tmp / "calls.log"
        for d in (self.home / "Library" / "LaunchAgents", self.home / "aikos" / "repo", self.tree, self.bin):
            d.mkdir(parents=True)
        for name, text in (("git", GIT), ("launchctl", LAUNCHCTL), ("curl", CURL)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.plist = self.home / "Library" / "LaunchAgents" / "home.aikos.tts.plist"
        self.releases = self.home / "aikos" / "releases" / "tts"

    def tag(self, tag: str, version: str, tests_pass: bool = True, *flags: str) -> None:
        src = self.tree / tag / "services" / "tts"
        (src / "deploy").mkdir(parents=True)
        (src / "tests").mkdir()
        (src / "deploy" / "install.sh").write_text(INSTALL)
        (src / "tests" / "test_release.py").write_text(f"def test_release():\n    assert {tests_pass}\n")
        (src / "VERSION").write_text(version)
        for flag in flags:
            (src / flag).write_text("")

    def running(self, version: str) -> Path:
        """A service already running from an older layout."""
        old = self.home / "aikos" / "services" / "tts"
        old.mkdir(parents=True)
        (old / "VERSION").write_text(version)
        self.plist.write_text(f"RELEASE={old}\n")
        return old

    def deploy(self, tag: str, **env: str) -> subprocess.CompletedProcess:
        full = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}:{os.environ['PATH']}", FAKE_TREE=str(self.tree),
                    FAKE_LOG=str(self.log), FAKE_PYTHON=sys.executable, AIKOS_HEALTH_WAIT_S="2",
                    PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", **env)      # the release's own tests: plain pytest, no plugins
        full.pop("PYTEST_ADDOPTS", None)
        return subprocess.run(["bash", str(DEPLOY), tag], capture_output=True, text=True, env=full, timeout=120)

    def calls(self) -> str:
        return self.log.read_text() if self.log.exists() else ""

    def deploy_log(self) -> str:
        return (self.home / "Library" / "Logs" / "aikos" / "deploy.log").read_text()


@pytest.fixture
def mac(tmp_path):
    return Mac(tmp_path)


def test_rolls_out_into_its_own_release_folder(mac):
    old = mac.running("0.5.0")
    mac.tag("tts-v0.6.0", "0.6.0")
    r = mac.deploy("tts-v0.6.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert mac.plist.read_text() == f"RELEASE={mac.releases / 'tts-v0.6.0'}\n"
    backups = list((mac.home / ".aikos" / "backup").glob("home.aikos.tts.plist.*"))
    assert [b.read_text() for b in backups] == [f"RELEASE={old}\n"]
    assert "OK: tts-v0.6.0 live, health 0.6.0, self-test passed" in mac.deploy_log()


def test_red_tests_change_nothing(mac):
    mac.running("0.5.0")
    before = mac.plist.read_text()
    mac.tag("tts-v0.6.0", "0.6.0", False)
    r = mac.deploy("tts-v0.6.0")
    assert r.returncode == 1
    assert mac.plist.read_text() == before and mac.calls() == ""
    assert "unit tests red, nothing changed" in mac.deploy_log()


def test_a_failed_build_changes_nothing(mac):
    mac.running("0.5.0")
    before = mac.plist.read_text()
    mac.tag("tts-v0.6.0", "0.6.0", True, "BUILD_FAIL")
    assert mac.deploy("tts-v0.6.0").returncode == 1
    assert mac.plist.read_text() == before and mac.calls() == ""


@pytest.mark.parametrize("flags, reason", [
    (("INSTALL_FAIL",), "the installer failed"),
    (("HEALTH_DOWN",), "health says version 'nothing', expected 0.6.0"),
    (("SELFTEST_FAIL",), "self-test failed"),
])
def test_a_failed_check_brings_back_the_previous_version(mac, flags, reason):
    old = mac.running("0.5.0")
    mac.tag("tts-v0.6.0", "0.6.0", True, *flags)
    r = mac.deploy("tts-v0.6.0")
    assert r.returncode == 1
    assert mac.plist.read_text() == f"RELEASE={old}\n"
    log = mac.deploy_log()
    assert f"ROLLBACK: {reason}" in log and "the previous version answers: 0.5.0" in log
    assert "launchctl bootstrap" in mac.calls()


def test_the_wrong_version_answering_is_a_failure(mac):
    """A tag whose code reports another version (or the old process still answering) is not accepted."""
    mac.running("0.5.0")
    mac.tag("tts-v0.6.0", "0.5.9")
    assert mac.deploy("tts-v0.6.0").returncode == 1
    assert "ROLLBACK: health says version '0.5.9', expected 0.6.0" in mac.deploy_log()


def test_a_failed_first_install_leaves_nothing_running(mac):
    mac.tag("tts-v0.6.0", "0.6.0", True, "SELFTEST_FAIL")
    assert mac.deploy("tts-v0.6.0").returncode == 1
    assert not mac.plist.exists()
    assert "there was no voice service before" in mac.deploy_log()


@pytest.mark.parametrize("tag, says", [("tts-v9.9.9", "no tag tts-v9.9.9"), ("transcriber-v1.3.2", "not a voice service tag")])
def test_unknown_or_foreign_tags_change_nothing(mac, tag, says):
    mac.running("0.5.0")
    before = mac.plist.read_text()
    assert mac.deploy(tag).returncode == 1
    assert mac.plist.read_text() == before and mac.calls() == ""
    assert says in mac.deploy_log()


def test_keeps_the_newest_releases(mac):
    mac.running("0.5.0")
    now = time.time()
    for i, tag in enumerate(("tts-v0.1.0", "tts-v0.2.0", "tts-v0.3.0", "tts-v0.4.0")):
        (mac.releases / tag).mkdir(parents=True)
        os.utime(mac.releases / tag, (now - 1000 + i, now - 1000 + i))
    mac.tag("tts-v0.6.0", "0.6.0")
    assert mac.deploy("tts-v0.6.0", AIKOS_KEEP="3").returncode == 0
    assert sorted(p.name for p in mac.releases.iterdir()) == ["tts-v0.3.0", "tts-v0.4.0", "tts-v0.6.0"]


def helper(name: str, call: str, stdin: str = "") -> subprocess.CompletedProcess:
    fn = re.search(rf"^{name}\(\) \{{.*\}}$", DEPLOY.read_text(), re.M).group(0)
    return subprocess.run(["bash", "-c", f"set -eu -o pipefail; {fn}; {call}"], input=stdin, capture_output=True, text=True)


def test_helpers():
    assert helper("version_of", "version_of tts-v0.6.0").stdout.strip() == "0.6.0"
    assert helper("version_of", "version_of transcriber-v1.3.2").stdout.strip() == ""
    assert helper("health_version", "health_version", '{"ok": true, "version" : "0.6.0", "engine": "chatterbox-mlx"}').stdout.strip() == "0.6.0"
    assert helper("health_version", "health_version", '{"ok": true}').stdout.strip() == ""
    assert helper("says_ok", "says_ok", '{"ok": true, "seconds": 2.1}').returncode == 0
    assert helper("says_ok", "says_ok", '{"ok": false}').returncode != 0
